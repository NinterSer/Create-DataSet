import requests
from bs4 import BeautifulSoup
import json
import pandas as pd
import os
from datetime import datetime, timedelta, timezone
import socket
import sys

from tinkoff.invest import Client, InstrumentStatus, InstrumentIdType, CandleInterval
from tinkoff.invest.constants import INVEST_GRPC_API
from tinkoff.invest.services import OperationsService

from email.parser import Parser
from functools import lru_cache
from urllib.parse import parse_qs, urlparse

import webbrowser

FINAM_COMPANY_ID = {
	'gazp':{'id':2, 'name':'Газпром', 'figi':'BBG004730RP0'}, #газпром
	'sber':{'id':3, 'name':'Сбербанк', 'figi':'BBG004730N88'}, #сбербанк
	'lkoh':{'id':121, 'name':'Лукойл', 'figi':'BBG004731032'}, #Лукойл
	'hydr':{'id':1644, 'name':'Русгидро', 'figi':'BBG00475K2X9'}, #Русгидро
	'sibn':{'id':243, 'name':'Газпром Нефть', 'figi':'BBG004S684M6'}, #ГазпромНефть 
}
TIME_ZONE = timezone(timedelta(hours=3), name='МСК')
MAX_LINE = 64*1024
MAX_HEADERS = 100
CONFIG = {}


with open('config.json', 'r', encoding='utf-8') as fh:
	CONFIG = json.load(fh)
	fh.close()

class News:
	list_news = []
	_position_ = 0 
	class New:
		def __init__(self, company_ID:int, ticker:str, name:str, text:str, date, y=0):
			self.company_ID	= company_ID
			self.ticker = ticker
			self.name = name
			self.text = text
			self.date = date
			self.y = y

		def __str__(self):
			return self.text
		def __repr__(self):
			return f'New(company_ID={self.company_ID}, ticker="{self.ticker}", name="{self.name}", text="{self.text}", date="{self.date}", y={self.y})'

		def get(self, type=dict):
			result = None
			match type:
				case dict:
					result = {
						'company_ID':self.company_ID,
						'ticker':self.ticker,
						'name':self.name,
						'text':self.text,
						'date':self.date
					}
			return result

	def __init__(self, company_ID:int, ticker:str, name:str):
		self.company_ID = company_ID
		self.ticker = ticker
		self.name = name
	def __iter__(self):
		return self
	def __next__(self):
		if self._position_ < len(self.list_news):
			new = self.list_news[self._position_]
			self._position_+=1
			return new
		else:
			self._position_=0
			raise StopIteration
	def __str__(self):
		return f'{self.name} ({self.ticker})'
	def __repr__(self):
		text = f'News(company_ID={self.company_ID}, ticker="{self.ticker}", name="{self.name}", list_news=['
		for new in self.list_news:
			text+=f'{repr(new)},'
		text+='])'
		return text

	def add(self, text:str, date, y:int=0):
		new = self.New(company_ID=self.company_ID, ticker=self.ticker, name=self.name, text=text, date=date, y=y)
		self.list_news.append(new)

	def next(self, endMessage=False):
		if self._position_ < len(self.list_news):
			new = self.list_news[self._position_]
			self._position_+=1
			return new
		elif endMessage:
			return None
		else:
			self._position_=0
			new = self.list_news[self._position_]
			return new

	def save(self, file=None, type='DateFrame'):
		file = f'{self.ticker}.cvs' if file==None else file
		match type:
			case 'DateFrame':
				df = pd.DataFrame(columns=['name', 'ticker', 'text', 'date', 'Y'])
				for new in self.list_news:
					df.loc[-1] = [new.name, new.ticker, new.text, new.date, new.y]
					df.index = df.index + 1	# shifting index
					df = df.sort_index()	# sorting by index
				df = df.iloc[::-1].reset_index(drop=True)
				df.to_csv(file, encoding='utf-8')
		return file

	def load(self, file):
		match file[-4:]:
			case '.cvs':
				df = pd.read_csv(file)
				self.name = df.loc[0,'name']
				self.ticker = df.loc[0,'ticker']
				self.company_ID = FINAM_COMPANY_ID[self.ticker]['id']
				del self.list_news[:]
				for i, stroke in df.iterrows():
					self.add(stroke['text'], stroke['date'], stroke['Y'])
		return self

'''
class Date:

	def __init__(self, second=0, minute=0, hour=0, day=0, month=0, year=0):
		self.second = second
		self.minute = minute
		self.hour = hour
		self.day = day
		self.month = month
		self.year = year
	def __str__(self):
		return self.get()
	def __repr__(self):
		return	f'Date(second={self.second}, minute={self.minute}, hour={self.hour}, day={self.day}, month={self.month}, year={self.year})'

	def get(self, type=str, symbols_date='.', symbols_clock=':'):
		if type==str:
			return f'{self.day if self.day>9 else f'0{self.day}'}{symbols_date}{self.month if self.month>9 else f'0{self.month}'}{symbols_date}{self.year} {self.hour if self.hour>9 else f'0{self.hour}'}{symbols_clock}{self.minute if self.minute>9 else f'0{self.minute}'}{symbols_clock}{self.second if self.second>9 else f'0{self.second}'}'
		elif type==dict:
			return {'second':self.second, 'minute':self.minute, 'hour':self.hour, 'day':self.day, 'month':self.month, 'year':self.year}
'''

class Candels:
	def __init__(self, figi, name, ticker, token=CONFIG['token'], t_ID=CONFIG['id'], timezone=CONFIG['time_zone_Moscow']):
		self.name = name
		self.figi = figi
		self.ticker = ticker
		self.token = token
		self.t_ID = t_ID
		self.timezone = timezone
		self.candels = None
		self.date = datetime.today()
		self.from_ = datetime.today()
		self.to = datetime.today()
		self._iter_position_ = 0

	def __next__(self):
		if self._iter_position_ < len(self.candels):
			candle = self.candels[self._iter_position_]
			self._iter_position_+=1
			return candle
		else:
			self._iter_position_=0
			raise StopIteration
		pass
	def __iter__(self):
		if self.candels == None:
			self.set()
		return self

	def set(self, date=datetime.today(), period=30, interval=CandleInterval.CANDLE_INTERVAL_1_MIN):
		self.date += timedelta(self.timezone)
		self.from_ = date-timedelta(minutes=round(period*0.3))
		self.to = date+timedelta(minutes=round(period*0.7))
		candels = None
		with Client(self.token) as client:
			self.candels = client.market_data.get_candles(figi=self.figi, from_=self.from_, to=self.to, interval=interval).candles
	
	def get(self, type=list):
		result = None
		match type:
			case list:
				result = []
				for candle in self.candels:
					time = candle.time + timedelta(hours=3+self.timezone)
					time = str(time).split('+')[0]
					candle = {
						'open':float(str(candle.open.units)+'.'+str(candle.open.nano)),
						'close':float(str(candle.close.units)+'.'+str(candle.close.nano)),
						'high':float(str(candle.high.units)+'.'+str(candle.high.nano)),
						'low':float(str(candle.open.units)+'.'+str(candle.open.nano)),
						'time':time
						}
					result.append(candle)

		return result

class HTTPServer:
	def __init__(self, host, port, server_name, site_directory, config, ACTIVE_NEWS=None):
		self._host = host
		self._port = port
		self._server_name = server_name
		self._users = {}
		self._site = f"./{site_directory}"
		self.ACTIVE_NEWS = ACTIVE_NEWS

	def serve_forever(self):
		serv_sock = socket.socket(
			socket.AF_INET,
			socket.SOCK_STREAM,
			proto=0)
		try:
			serv_sock.bind((self._host, self._port))
			serv_sock.listen()
			while True:
				conn, _ = serv_sock.accept()
				try:
					self.serve_client(conn)
				except Exception as e:
					print('Client serving failed', e)
		finally:
			serv_sock.close()

	def serve_client(self, conn):
		try:
			req = self.parse_request(conn)
			resp = self.handle_request(req)
			self.send_response(conn, resp)
		except ConnectionResetError:
			conn = None
		except Exception as e:
			self.send_error(conn, e)
		if conn:
			conn.close()


	def parse_request(self, conn):
		method, target, ver, headers, rfile = None, None, None, None, None
		rfile = b''
		res = b''
		head = True
		while True:
			packet = conn.recv(MAX_LINE)
			res+= packet
			if head:
				method, target, ver, headers, rfile = self.parse_headers(packet)
				head = False
				if method == 'GET' or (method == 'POST' and len(rfile)==headers['Content-Length']): break
			elif len(res)<headers['Content-Length']:
				rfile += packet
			else:
				rfile += packet
				break
		host = headers['Host']
		if not host:
			raise HTTPError(400, 'Bad request',
				'Host header is missing')
		if host not in (self._server_name,f'{self._server_name}:{self._port}'):
			raise HTTPError(404, 'Not found')
		return Request(method, target, ver, headers, rfile)

	def parse_headers(self, text):
		method, target, ver, rfile = None, None, None, None
		headers = {}
		this_first = True
		text = text.split(b'\r\n\r\n')
		for line in text[0].split(b'\r\n'):
			line = str(line, 'UTF-8')
			if this_first:
				method, target, ver = line.split()
				this_first = False
			elif ':' in line:
				try:
					try:
						headers[line.split(': ')[0]] = int(line.split(': ')[1])
					except:
						headers[line.split(': ')[0]] = line.split(': ')[1]
				except:
					headers[line.split(': ')[0]] = None
		if(len(text)>1):
			rfile = text[1]
		return method, target, ver, headers, rfile
	

	def get_html_page(self):
		contentType = 'text/html; charset=UTF-8'
		body = open(f"{self._site}/index.html", encoding='utf-8').read()
		body = body.encode('utf-8')
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def get_js_file(self, req):
		contentType = 'application/javascript; charset=UTF-8'
		body = open(f"{self._site}{req.path}", encoding='utf-8').read()
		body = body.encode('utf-8')
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def get_css_file(self, req):
		contentType = 'text/css; charset=UTF-8'
		body = open(f"{self._site}{req.path}").read()
		body = body.encode('utf-8')
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def get_png_file(self, req):
		contentType = 'image/png; charset=UTF-8'
		body = open(f"{self._site}{req.path}",'rb').read()
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def get_test(self, req):
		if req.method == 'POST':
			contentType = 'application/json; charset=UTF-8'
			data = json.loads(str(req.rfile, 'utf-8'))
			body = json.dumps(data)
			body = body.encode('utf-8')
			headers = [('Content-Type', contentType),('Content-Length', len(body))]
			return Response(200, 'OK', headers, body)

	def get_list_DataSets(self, req):
		contentType = "text/html; charset=UTF-8"
		body = {'list':[]}
		for f in os.listdir('./'):
			if f[-4:] == '.cvs':
				body['list'].append(f)
		body = json.dumps(body)
		body = body.encode('utf-8')
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def get_news(self, req):
		contentType = "text/html; charset=UTF-8"
		data = json.loads(str(req.rfile, 'utf-8'))
		body = self.get_news_repeat(data, True)
		body = json.dumps(body)
		body = body.encode('utf-8')
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def get_news_repeat(self, data, empty_candels=True):
		#news = News(company_ID=2, ticker='test', name='test')
		#news.load(data['file'])
		body = self.ACTIVE_NEWS.list_news[data['position']].get()
		body['file'] = data['file']
		body['position'] = data['position']
		body['length'] = len(self.ACTIVE_NEWS.list_news)
		candels = Candels(FINAM_COMPANY_ID[self.ACTIVE_NEWS.ticker]['figi'], FINAM_COMPANY_ID[self.ACTIVE_NEWS.ticker]['name'], self.ACTIVE_NEWS.ticker)
		candels.set(datetime.strptime(body['date'],'%Y-%m-%d %H:%M:%S'))
		body['candels'] = candels.get()
		if len(candels.candels)>0:
			return body
		else:
			#news = News(company_ID=2, ticker='test', name='test')
			#news.load(data['file'])
			body = self.ACTIVE_NEWS.list_news[data['position']].get()
			body['file'] = data['file']
			body['position'] = data['position']
			body['length'] = len(self.ACTIVE_NEWS.list_news)
			candels = Candels(FINAM_COMPANY_ID[self.ACTIVE_NEWS.ticker]['figi'], FINAM_COMPANY_ID[self.ACTIVE_NEWS.ticker]['name'], self.ACTIVE_NEWS.ticker)
			date = datetime.strptime(body['date'],'%Y-%m-%d %H:%M:%S').replace(minute=0,second=0)
			body['date'] = str(date)
			candels.set(date, 1200, CandleInterval.CANDLE_INTERVAL_HOUR)
			body['candels'] = candels.get()

			if len(candels.candels)>0 or empty_candels:
				return body
			else:
				body['position']+=1
				return self.get_news_repeat(body)

	def parcing(self, req):
		contentType = "text/html; charset=UTF-8"
		data = json.loads(str(req.rfile, 'utf-8'))
		FINAM_COMPANY_ID[data['ticker']] = {}
		FINAM_COMPANY_ID[data['ticker']]['id'] = data['id']
		FINAM_COMPANY_ID[data['ticker']]['name'] = data['name']
		FINAM_COMPANY_ID[data['ticker']]['figi'] = data['figi']
		news = create_news(ticker=data['ticker'], start=data['start'], end=data['end'], step=data['step'])
		file = news.save()
		body = json.dumps({'length':len(news.list_news),'file':file})
		body = body.encode('utf-8')
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def set_news(self, req):
		contentType = "text/html; charset=UTF-8"
		data = json.loads(str(req.rfile, 'utf-8'))
		#news = News(company_ID=2, ticker='test', name='test')
		#news.load(data['file'])
		if self.ACTIVE_NEWS == None:
			self.ACTIVE_NEWS = News(company_ID=2, ticker='test', name='test')
			self.ACTIVE_NEWS.load(data['file'])
		self.ACTIVE_NEWS.list_news[data['position']].y = data['y']
		#file = news.save()
		body = {}
		body['position'] = data['position']
		body['length'] = len(self.ACTIVE_NEWS.list_news)
		body = json.dumps(body)
		body = body.encode('utf-8')
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def load_file(self, req):
		contentType = "text/html; charset=UTF-8"
		data = json.loads(str(req.rfile, 'utf-8'))
		if self.ACTIVE_NEWS != None:
			self.ACTIVE_NEWS.save()
		self.ACTIVE_NEWS = News(company_ID=2, ticker='test', name='test')
		self.ACTIVE_NEWS.load(data['file'])
		body = json.dumps({'length':len(self.ACTIVE_NEWS.list_news),'file':data['file']})
		body = body.encode('utf-8')
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def save_file(self, req):
		contentType = "text/html; charset=UTF-8"
		file = self.ACTIVE_NEWS.save()
		body = json.dumps({'file':file})
		body = body.encode('utf-8')
		headers = [('Content-Type', contentType),('Content-Length', len(body))]
		return Response(200, 'OK', headers, body)

	def handle_request(self, req):
		if req.method == 'GET': 
			if req.path == '/index.php':
				return self.get_html_page()
			elif req.path[-3:] == 'css':
				return self.get_css_file(req)
			elif req.path[-2:] == 'js':
				return self.get_js_file(req)
			elif req.path[-3:] == 'png':
				return self.get_png_file(req)
		elif req.method == 'POST':
			if req.path == '/test':
				return self.get_test(req)
			elif req.path == '/getListDataSets':
				return self.get_list_DataSets(req)
			elif req.path == '/getNews':
				return self.get_news(req)
			elif req.path == '/parcing':
				return self.parcing(req)
			elif req.path == '/setNews':
				return self.set_news(req)
			elif req.path == '/loadFile':
				return self.load_file(req)
			elif req.path == '/saveFile':
				return self.save_file(req)


		raise HTTPError(404, 'Not found')

	def send_response(self, conn, resp):
		wfile = conn.makefile('wb')
		http = ''
		line = ''
		status_line = f'HTTP/1.1 {resp.status} {resp.reason}\r\n'
		wfile.write(status_line.encode('utf-8'))

		if resp.headers:
			for (key, value) in resp.headers:
				header_line = f'{key}: {value}\r\n'
				line += f'{key}: {value}\r\n'
				wfile.write(header_line.encode('utf-8'))
		wfile.write(b'\r\n')

		if resp.body:
			wfile.write(resp.body)

		wfile.flush()
		wfile.close()

	def send_error(self, conn, err):
		try:
			status = err.status
			reason = err.reason
			body = (err.body or err.reason).encode('utf-8')
		except:
			status = 500
			reason = b'Internal Server Error'
			body = b'Internal Server Error'
		resp = Response(status, reason,
						 [('Content-Length', len(body))],
						 body)
		self.send_response(conn, resp)

		def handle_post_users(self, req):
			user_id = len(self._users) + 1
			self._users[user_id] = {'id': user_id,
									'name': req.query['name'][0],
									'age': req.query['age'][0]}
			return Response(204, 'Created')

class Request:
	def __init__(self, method, target, version, headers, rfile):
		self.method = method
		self.target = target
		self.version = version
		self.headers = headers
		self.rfile = rfile

	@property
	def path(self):
		return self.url.path

	@property
	@lru_cache(maxsize=None)
	def query(self):
		return parse_qs(self.url.query)

	@property
	@lru_cache(maxsize=None)
	def url(self):
		return urlparse(self.target)

	def body(self):
		size = self.headers.get('Content-Length')
		if not size:
			return None
		return self.rfile.read(size)

class Response:
	def __init__(self, status, reason, headers=None, body=None):
		self.status = status
		self.reason = reason
		self.headers = headers
		self.body = body

class HTTPError(Exception):
	def __init__(self, status, reason, body=None):
		super()
		self.status = status
		self.reason = reason
		self.body = body

def get_date(text):
	text = text.split('/')[-2].split('-')[-2:]
	try:
		int(text[0])
		int(text[1])
	except:
		return False

	date = datetime(minute=int(text[1][2:4]), hour=int(text[1][0:2]), day=int(text[0][6:8]), month=int(text[0][4:6]), year=int(text[0][0:4]))
	return date

def create_news(ticker, start=0, end=100, step=50):
	company = FINAM_COMPANY_ID[ticker]
	news = News(company_ID=company['id'], ticker=ticker, name=company['name'])

	url = 'https://www.finam.ru/plugin/'
	headers = {
		'Accept': 'application/json',
		'Cookie': 'spid=1735779963131_efe89fc8cb5fd2460602684450432b63_720uv1stju07dqes; spsc=1735779963131_558aacdbaf8727439938a698ae5070f8_e6cfb3ea8f0a0fa28cc6ebefdcae8ea5; _ym_uid=1735779964844262979; _ym_d=1751884213; tmr_lvid=697647d8c1fbd0d95b42a5a151b103d1; tmr_lvidTS=1735779964051; offfyUserId=1751884214231-0160-19458bc96e1c; _pk_id.19.2ab2=29c3c99f8ec0e399.1751884215.; domain_sid=NHFitxHEwX7xSGGRChUYU%3A1751884215115; cookie_policy_accepted=accepted; proxy=1; _ym_isad=2; _pk_ref.19.2ab2=%5B%22%22%2C%22%22%2C1751965727%2C%22https%3A%2F%2Fyandex.by%2F%22%5D; tmr_detect=0%7C1751965728597; spsc=1751968056071_aa1a7ce8e0f569594209e1abbd3f9abe_lMOhfPLvw6IgpZbcGY-Jz.w0MfeWAgCWGcvniQBAga0Z; tx-auth-widget%3Aauth-stamp%3Afinam%3A452acafcda3a48973e077464276fb13c=finamRu%3A1751969112269',
		'Host': 'www.finam.ru',
		'Origin': 'https://www.finam.ru',
		'Referer': f'https://www.finam.ru/quote/moex/{ticker}/publications/',
		#'Sec-Fetch-Dest': 'empty',
		#'Sec-Fetch-Mode': 'cors',
		#'Sec-Fetch-Site': 'same-origin',
		'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 YaBrowser/25.6.0.0 Safari/537.36',
		'Content-Type': 'application/json; charset=UTF-8',
		'X-Requested-With': 'XMLHttpRequest',
		#'sec-ch-ua': '"Chromium";v="136", "YaBrowser";v="25.6", "Not.A/Brand";v="99", "Yowser";v="2.5"',
		#'sec-ch-ua-mobile': '?0',
		#'sec-ch-ua-platform': "Windows"
	}
	data = {
		"plugin": "publication",
		"method": "list",
		"template": "transformer",
		"response": "mixTeleport",
		"params": {
			"addFavorites": True,
			#"id": 16842,
			#"quoteTitle": "ГАЗПРОМ ао: новости",
			"portrait": {
				"all": [],
				"any": [
					#"quote-5239179",
					f"company-{company['id']}"
				],
				"like": 'null',
				"text": 'null'
			},
			#"quoteId": 5239179,
			"companyId": company['id'],
			"limit": step,
			"offset": start,
			"dateFrom": 'null',
			"dateTo": 'null',
			"selectedTab": "publications",
			"IsModerator": False,
			"enrich": [
				"section",
				"author"
			],
			"view": {
				"more": 1,
				"parent": None
			},
			"look": {
				"empty": {},
				"item": {
					"class": "mb2x",
					"content": {
						"class": "",
						"link": {
							"class": "cl-blue font-l bold"
						},
						"date": {
							"class": "font-xs cl-darkgrey"
						},
						"author": {
							"class": "font-xs cl-darkgrey before-content-dot-grey",
							"company": {
								"class": "before-content-comma"
							},
							"position": {
								"class": "hide"
							}
						},
						"section": {
							"class": "font-xs cl-darkgrey before-content-dot-grey"
						},
						"image": {
							"class": "hide"
						},
						"annoncement": {
							"class": "font-s cl-black"
						}
					},
					"quote": {
						"class": "mr1x font-xs nowrap"
					}
				}
			}
		}
	}
	for i in range(start, end, step):
		data['params']['offset'] = i
		try:
			response = requests.post(url, headers=headers, data=json.dumps(data))
			html = json.loads(response.text)['html']
			soup = BeautifulSoup(html, "html.parser")
			news_html = soup.findAll('div', class_='mb2x')
			for new in news_html:
				new = new.findAll('a', class_='cl-blue font-l bold')
				link = new[0].attrs.get("href")
				text = new[1].text
				date = get_date(link)
				if not date:
					continue
				news.add(text=text, date=date)
		except:
			continue	
		os.system('cls')
		print(i/(end-start)*100)
	return news

if __name__ == '__main__':
	webbrowser.open('http://127.0.0.1:8081/index.php', new=2)
	server = HTTPServer('127.0.0.1', 8081, '127.0.0.1', 'site', CONFIG, None)
	server.serve_forever()



