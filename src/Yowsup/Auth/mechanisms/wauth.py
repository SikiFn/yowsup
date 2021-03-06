'''
Copyright (c) <2012> Tarek Galal <tare2.galal@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of this 
software and associated documentation files (the "Software"), to deal in the Software 
without restriction, including without limitation the rights to use, copy, modify, 
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to 
permit persons to whom the Software is furnished to do so, subject to the following 
conditions:

The above copyright notice and this permission notice shall be included in all 
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, 
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR 
A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT 
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF 
CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE 
OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''

import socket, hashlib, hmac
from Yowsup.Tools.debugger import Debugger
from Yowsup.Tools.watime import WATime
from Yowsup.ConnectionIO.protocoltreenode import ProtocolTreeNode
from Yowsup.Tools.datastructures import ByteArray

from struct import pack
from operator import xor
from itertools import izip, starmap
from hashlib import sha1


def _bytearray(data):

	if type(data) == str:
		return data
	elif type(data) == list:
		tmp = [chr(x) if type(x) == int else x for x in data]
		return "".join(tmp)
	elif type(data) == int:
		tmp = ""
		#for i in range(0,data):
		#	tmp = tmp + chr(0)
		#	return tmp
		return [0] * data

	return ""

class WAuth():

	def __init__(self,conn):
		Debugger.attach(self);

		self.conn = conn
		self._d("Yowsup WAUTH-1 INIT");

	def setAuthObject(self, authObject):
		self.authObject = authObject
	
	def login(self, username, password, domain, resource):

		self.username = username

		try:
			self._d("Starting stream")
			self.conn.writer.streamStart(domain,resource);

			self._d("Sending Features")
			self.sendFeatures();

			self._d("Sending Auth");
			self.sendAuth();

			self._d("Read stream start");
			self.conn.reader.streamStart();

			self._d("Read features and challenge");
			challengeData = self.readFeaturesAndChallenge();

			self._d("Sending Response")
			self.sendResponse(challengeData);

			self._d("Read success")
			
			if not self.readSuccess(): return 0

			self.conn.jid = "%s@%s" % (username, domain)
			return self.conn

		except socket.error:
			return self.connectionError.emit()


	def sendFeatures(self):
		toWrite = ProtocolTreeNode("stream:features",None,[ ProtocolTreeNode("receipt_acks",None,None),ProtocolTreeNode("w:profile:picture",{"type":"all"},None), ProtocolTreeNode("w:profile:picture",{"type":"group"},None),ProtocolTreeNode("notification",{"type":"participant"},None), ProtocolTreeNode("status",None,None) ])


		self.conn.writer.write(toWrite);

	def sendAuth(self):
		# "user":self.connection.user,
		blob = []
		node = ProtocolTreeNode("auth",{"user":self.username,"xmlns":"urn:ietf:params:xml:ns:xmpp-sasl","mechanism":"WAUTH-1"}, None, ''.join(map(chr, blob)));
		self.conn.writer.write(node);

	def readFeaturesAndChallenge(self):
		root = self.conn.reader.nextTree();

		while root is not None:
			if ProtocolTreeNode.tagEquals(root,"stream:features"):
				self._d("GOT FEATURES !!!!");
				self.authObject.supportsReceiptAcks  = root.getChild("receipt_acks") is not None;
				root = self.conn.reader.nextTree();

				continue;

			if ProtocolTreeNode.tagEquals(root,"challenge"):
				self._d("GOT CHALLENGE !!!!");
				#data = base64.b64decode(root.data);
				return root.data;
		raise Exception("fell out of loop in readFeaturesAndChallenge");


	def sendResponse(self,challengeData):

		authBlob = self.getAuthBlob(challengeData);
		node = ProtocolTreeNode("response",{"xmlns":"urn:ietf:params:xml:ns:xmpp-sasl"}, None, authBlob);
		self.conn.writer.write(node);
		self.conn.reader.inn.buf = [];

	def getAuthBlob(self, nonce):
		numArray = _bytearray(KeyStream.keyFromPasswordAndNonce(self.authObject.password, nonce))
		self.conn.reader.inputKey = self.inputKey = KeyStream(numArray)
		self.outputKey = KeyStream(numArray)

		nums = []

		for i in range(0,4):
			nums.append(0)

		nums.extend(self.username)
		nums.extend(nonce)

		wt = WATime()
		utcNow = int(wt.utcTimestamp())
		nums.extend(str(utcNow))

		encoded = self.outputKey.encodeMessage(nums, 0, 4, len(nums) - 4)
		encoded = "".join(map(chr, encoded))

		return encoded

	def readSuccess(self):
		node = self.conn.reader.nextTree();
		self._d("Login Status: %s"%(node.tag));

		if ProtocolTreeNode.tagEquals(node,"failure"):
			self.authObject.authenticationFailed()
			return 0
			#raise Exception("Login Failure");

		ProtocolTreeNode.require(node,"success");

		expiration = node.getAttributeValue("expiration");

		if expiration is not None:
			self._d("Expires: "+str(expiration));
			self.authObject.expireDate = expiration;

		kind = node.getAttributeValue("kind");
		self._d("Account type: %s"%(kind))

		if kind == "paid":
			self.authObject.accountKind = 1;
		elif kind == "free":
			self.authObject.accountKind = 0;
		else:
			self.authObject.accountKind = -1;

		status = node.getAttributeValue("status");
		self._d("Account status: %s"%(status));

		if status == "expired":
			self.loginFailed.emit()
			raise Exception("Account expired on "+str(self.authObject.expireDate));

		if status == "active":
			if expiration is None:
				#raise Exception ("active account with no expiration");
				'''@@TODO expiration changed to creation'''
		else:
			self.authObject.accountKind = 1;

		self.conn.reader.inn.buf = [];

		self.conn.writer.outputKey = self.outputKey
		self.authObject.authenticationComplete()
		return 1


class RC4:
	def __init__(self, key, drop):
		self.s = []
		self.i = 0;
		self.j = 0;
		
		self.s = [0] * 256
		
		for i in range(0, len(self.s)):
			self.s[i] = i
		
		for i in range(0, len(self.s)):
			self.j = (self.j + self.s[i] + ord(key[i % len(key)])) % 256
			RC4.swap(self.s, i, self.j)
		
		self.j = 0;
		
		self.cipher(_bytearray(drop), 0, drop)
	
	
	def cipher(self, data, offset, length):
		while True:
			num = length
			length = num - 1
			
			if num == 0: break
			
			self.i = (self.i+1) % 256
			self.j = (self.j + self.s[self.i]) % 256
			
			RC4.swap(self.s, self.i, self.j)
			
			num2 = offset
			offset = num2 + 1

			data[num2] = ord(data[num2]) if type(data[num2]) == str else data[num2]
			data[num2] = (data[num2] ^ self.s[(self.s[self.i] + self.s[self.j]) % 256])
	
	@staticmethod
	def swap(arr, i, j):
		tmp = arr[i]
		arr[i] = arr[j]
		arr[j] = tmp



class KeyStream:

	def __init__(self, key):
		self.key = key
		self.rc4 = RC4(key, 256)

	def decodeMessage(self, bufdata, macOffset, offset, length):

		buf = bufdata[:]
		hashed = hmac.new(buffer(self.key), buffer(_bytearray(buf[offset:])), sha1)
		numArray = hashed.digest()

		numArray = [ord(x) for x in numArray];

		rest2 = bufdata[0:offset]
		rest2.extend(numArray)

		num = 0
		while num < 4:
			if buf[macOffset + num] == rest2[num]:
				num += 1
			else:
				raise Exception("INVALID MAC")

		self.rc4.cipher(buf, offset, length)

		return [x for x in buf]

	def encodeMessage(self, buf, macOffset, offset, length):
		#buf = _bytearray(buf)
		self.rc4.cipher(buf, offset, length)

		hashed = hmac.new(buffer(self.key), buffer(_bytearray(buf[offset:length+offset])), sha1)
		numArray = hashed.digest()#binascii.b2a_base64(hashed.digest())[:-1]
		numArray = [ord(x) for x in numArray]
		
		for i in range(0,4):
			buf[macOffset + i] = numArray[i]

		return [x for x in buf]

	@staticmethod
	def keyFromPasswordAndNonce(password, nonce):
		return KeyStream.pbkdf2(password, nonce, 16, 20)

	@staticmethod
	def pbkdf2( password, salt, itercount, keylen, hashfn = hashlib.sha1 ):
	
		def pbkdf2_F( h, salt, itercount, blocknum ):
	
			def prf( h, data ):
				hm = h.copy()
				hm.update( buffer(_bytearray(data)) )
				return map(ord, hm.digest())
	
			U = prf( h, salt + pack('>i',blocknum ) )
			T = U
	
			for i in range(2, itercount+1):
				U = prf( h, U )
				T = starmap(xor, izip(T, U))
	
			return T
	
		digest_size = hashfn().digest_size
		l = keylen / digest_size
		if keylen % digest_size != 0:
			l += 1
	
		h = hmac.new( password, None, hashfn )
	
		T = []
		for i in range(1, l+1):
			T.extend(pbkdf2_F( h, salt, itercount, i ))
	
		T = [chr(i) for i in T]
		return "".join(T[0: keylen])


if __name__ == "__main__":


	print [ord(i) for i in KeyStream.pbkdf2("tarek", "galal", 16, 20)]
	
	#test1 = KeyStream.keyFromPasswordAndNonce("hamada", bytearray([116,97,116,97,116,97,116,97]))
	#for r in test1:
	#    print ord(r)
	'''
	key = bytearray([116,97,116,97,116,97,116,97])
	#toenc = bytearray([0,0,0,0,114,101,107, 114,101,107])
	toenc = bytearray([0, 0, 0, 248, 3, 144, 203, 18, 0, 0, 0, 0])




	
	hashed = hmac.new(key, toenc[3:], sha1)
	numArray = hashed.digest()#binascii.b2a_base64(hashed.digest())[:-1]
	numArray = [ord(x) for x in numArray]
	print "NARRAY"
	print numArray
	

	
	#r = RC4(key, 256)
	#r.cipher(toenc, 3, 3)
	#res = r.encrypt("".join(map(chr, [114,101,107])), "".join(map(chr,[116,97,116,97,116,97,116,97])))
	#print [x for x in toenc]

	k = KeyStream(key)

	#res = self.outputKey.encodeMessage(prep, len(prep) - 4 , 3, len(prep)-4-3)
	res = k.encodeMessage(toenc, len(toenc) - 4, 3, len(toenc) - 4 -3)
	#res = k.encodeMessage(toenc, 0, 4, len(toenc) - 4)
	print [t for t in toenc]
	print res
	#dec = k.decodeMessage(bytearray(res), 0, 4, len(bytearray(res))-4)
	
	#print dec'''