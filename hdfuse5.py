#!/usr/bin/env python

# Copyright (c) 2011 Tobias Richter <Tobias.Richter@diamond.ac.uk>
# 
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
# 
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

from __future__ import with_statement

from errno import EACCES
from sys import argv, exit
from threading import Lock

import os
import h5py

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

#class HDFuse5(LoggingMixIn, Operations):    
class HDFuse5(Operations):    

	def __init__(self, root):
		self.root = os.path.realpath(root)
		self.rwlock = Lock()

	def __call__(self, op, path, *args):
		return super(HDFuse5, self).__call__(op, self.root + path, *args)

	class PotentialHDFFile:
		def __init__(self, path):
			self.dsattrs = { 	"user.ndim" : (lambda x : x.value.ndim), 
						"user.shape" : (lambda x : x.value.shape), 
						"user.dtype" : (lambda x : x.value.dtype), 
						"user.size" : (lambda x : x.value.size), 
						"user.itemsize" : (lambda x : x.value.itemsize), 
						"user.dtype.itemsize" : (lambda x : x.value.dtype.itemsize),
					}
			self.fullpath = path
			self.nexusfile = None
			self.nexushandle = None
			self.internalpath = "/"
			if os.path.lexists(path):
				self.testHDF(path)
			else:
				components = path.split("/")
				for i in range(len(components),0,-1):
					test = "/".join(components[:i])
					if self.testHDF(test):
						self.internalpath = "/".join(components[i-len(components):])
						#print self.internalpath
						break

		def testHDF(self, path):
			if os.path.isfile(path):
				try:
					self.nexushandle = h5py.File(path,'r')
					self.nexusfile = path
					#print path + " is hdf"
					return True
				except:
					pass
				return False

		def __del__(self):
			if self.nexushandle != None:
				try:
					#print "closing handle for "+self.fullpath
					self.nexushandle.close()
				except:
					pass

		def makeIntoDir(self, statdict):
			statdict["st_mode"] = statdict["st_mode"] ^ 0100000 | 0040000
			for i in [ [ 0400 , 0100 ] , [ 040 , 010 ] , [ 04, 01 ] ]:
				if (statdict["st_mode"] & i[0]) != 0:
					statdict["st_mode"] = statdict["st_mode"] | i[1]
			return statdict

		def getattr(self):
			if self.nexusfile != None:
				st = os.lstat(self.nexusfile)
			else:
				st = os.lstat(self.fullpath)
			statdict = dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
				'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))
			if self.nexusfile != None:
				if self.internalpath == "/":
					statdict = self.makeIntoDir(statdict)
				elif isinstance(self.nexushandle[self.internalpath],h5py.Group):
					statdict = self.makeIntoDir(statdict)
					statdict["st_size"] = 0
				elif isinstance(self.nexushandle[self.internalpath],h5py.Dataset):
					ob=self.nexushandle[self.internalpath].value
					statdict["st_size"] = ob.size * ob.itemsize
			return statdict	

		def getxattr(self, name):
			if self.nexushandle == None:
				return ""
			rawname = name[5:]
			if rawname in self.nexushandle[self.internalpath].attrs.keys():
				return self.nexushandle[self.internalpath].attrs[rawname].__str__()
			if isinstance(self.nexushandle[self.internalpath],h5py.Dataset):
				if name in self.dsattrs.keys():
					return self.dsattrs[name](self.nexushandle[self.internalpath]).__str__()
			return ""

		def listxattr(self):
			if self.nexushandle == None:
				return []
			xattrs = []
			for i in self.nexushandle[self.internalpath].attrs.keys():
					xattrs.append("user."+i)
			if isinstance(self.nexushandle[self.internalpath],h5py.Dataset):
				for i in self.dsattrs.keys():
					xattrs.append(i)
			return xattrs

		def listdir(self):
			if self.nexushandle == None:
				return ['.', '..'] + os.listdir(self.fullpath)
			else:
				items = self.nexushandle[self.internalpath].items()
				return ['.', '..'] + list((a[0]) for a in items)

		def access(self, mode):
			path = self.fullpath
			if self.nexusfile != None:
				path = self.nexusfile
				if mode == os.X_OK:
					mode = os.R_OK
			if not os.access(path, mode):
	                        raise FuseOSError(EACCES)

		def read(self, size, offset, fh, lock):
			if self.nexushandle == None or self.internalpath == "/":
				with lock:
					os.lseek(fh, offset, 0)
				return os.read(fh, size)
			if isinstance(self.nexushandle[self.internalpath],h5py.Dataset):
				return self.nexushandle[self.internalpath].value.tostring()[offset:offset+size]

		def open(self, flags):
			if self.nexushandle == None or self.internalpath == "/":
				return os.open(self.fullpath, flags)
			return 0

		def close(self, fh):
			if self.nexushandle == None or self.internalpath == "/":
				return os.close(fh)
			return 0

	def access(self, path, mode):
		self.PotentialHDFFile(path).access(mode);

	def read(self, path, size, offset, fh):
		return self.PotentialHDFFile(path).read(size, offset, fh, self.rwlock)

	def getattr(self, path, fh=None):
		return self.PotentialHDFFile(path).getattr();

	def getxattr(self, path, name):
		return self.PotentialHDFFile(path).getxattr(name);

	def listxattr(self, path):
		return self.PotentialHDFFile(path).listxattr();

	def readdir(self, path, fh):
		return self.PotentialHDFFile(path).listdir();

	def release(self, path, fh):
		return self.PotentialHDFFile(path).close(fh);

	def statfs(self, path):
		stv = os.statvfs(path)
		return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
			'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
			'f_frsize', 'f_namemax'))

	def open(self, path, flags):
		return self.PotentialHDFFile(path).open(flags);

	truncate = None
	write = None
	rename = None
	symlink = None
	setxattr = None
	removexattr = None
	link = None
	mkdir = None
	mknod = None
	rmdir = None
	unlink = None
	chmod = None
	chown = None
	create = None
	fsync = None
	flush = None
	utimens = os.utime
	readlink = os.readlink

if __name__ == "__main__":
	if len(argv) != 3:
		print 'usage: %s <root> <mountpoint>' % argv[0]
		exit(1)
	#signal.signal(signal.SIGINT, signal.SIG_DFL)
	#fuse = FUSE(HDFuse5(argv[1]), argv[2], foreground=True)
	fuse = FUSE(HDFuse5(argv[1]), argv[2])
