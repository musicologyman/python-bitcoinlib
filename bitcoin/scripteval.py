
#
# scripteval.py
#
# Distributed under the MIT/X11 software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#

import copy
from serialize import Hash, Hash160, ser_uint256, ser_uint160
from Crypto.Hash import SHA256
from script import *
from core import CTxOut
from key import CKey
from bignum import bn2vch, vch2bn

def SignatureHash(script, txTo, inIdx, hashtype):
	if inIdx >= len(txTo.vin):
		return (0L, "inIdx %d out of range (%d)" % (inIdx,len(txTo.vin)))
	txtmp = copy.deepcopy(txTo)
	for txin in txtmp.vin:
		txin.scriptSig = ''
	txtmp.vin[inIdx].scriptSig = script.vch

	if (hashtype & 0x1f) == SIGHASH_NONE:
		txtmp.vout = []

		for i in xrange(len(txtmp.vin)):
			if i != inIdx:
				txtmp.vin[i].nSequence = 0

	elif (hashtype & 0x1f) == SIGHASH_SINGLE:
		outIdx = inIdx
		if outIdx >= len(txtmp.vout):
			return (0L, "outIdx %d out of range (%d)" % (outIdx,len(txtmp.vout)))

		tmp = txtmp.vout[outIdx]
		txtmp.vout = []
		for i in xrange(outIdx):
			txtmp.vout.append(CTxOut())
		txtmp.vout.append(tmp)

		for i in xrange(len(txtmp.vin)):
			if i != inIdx:
				txtmp.vin[i].nSequence = 0

	if hashtype & SIGHASH_ANYONECANPAY:
		tmp = txtmp.vin[inIdx]
		txtmp.vin = []
		txtmp.vin.append(tmp)

	s = txtmp.serialize()
	s += struct.pack("<I", hashtype)

	hash = Hash(s)

	return (hash,)

def CheckSig(sig, pubkey, script, txTo, inIdx, hashtype):
	key = CKey()
	key.set_pubkey(pubkey)

	if len(sig) == 0:
		return False
	if hashtype == 0:
		hashtype = ord(sig[-1])
	elif hashtype != ord(sig[-1]):
		return False
	sig = sig[:-1]

	tup = SignatureHash(script, txTo, inIdx, hashtype)
	if tup[0] == 0L:
		return False
	return key.verify(ser_uint256(tup[0]), sig)

def dumpstack(msg, stack):
	print "%s stacksz %d" % (msg, len(stack))
	for i in xrange(len(stack)):
		vch = stack[i]
		print "#%d: %s" % (i, vch.encode('hex'))

def EvalScript(stack, scriptIn, txTo, inIdx, hashtype):
	script = CScript(scriptIn)
	while script.pc < script.pend:
		if not script.getop():
			return False
		sop = script.sop

		if sop.op <= OP_PUSHDATA4:
			stack.append(sop.data)
			continue

		elif sop.op == OP_1NEGATE or ((sop.op >= OP_1) and (sop.op <= OP_16)):
			v = sop.op - (OP_1 - 1)
			stack.append(bn2vch(v))

		elif sop.op == OP_2OVER:
			if len(stack) < 4:
				return False
			v1 = stack[-4]
			v2 = stack[-3]
			stack.append(v1)
			stack.append(v2)

		elif sop.op == OP_2SWAP:
			if len(stack) < 4:
				return False
			tmp = stack[-4]
			stack[-4] = stack[-2]
			stack[-2] = tmp

			tmp = stack[-3]
			stack[-3] = stack[-1]
			stack[-1] = tmp

		elif sop.op == OP_CHECKSIG or sop.op == OP_CHECKSIGVERIFY:
			if len(stack) < 2:
				return False
			vchPubKey = stack.pop()
			vchSig = stack.pop()
			tmpScript = CScript(script.vch[script.pbegincodehash:script.pend])

			# FIXME: find-and-delete vchSig

			ok = CheckSig(vchSig, vchPubKey, tmpScript,
				      txTo, inIdx, hashtype)
			if ok:
				if sop.op != OP_CHECKSIGVERIFY:
					stack.append("\x01")
			else:
				if sop.op == OP_CHECKSIGVERIFY:
					return False
				stack.append("\x00")

		elif sop.op == OP_CODESEPARATOR:
			script.pbegincodehash = script.pc

		elif sop.op == OP_DROP:
			if len(stack) < 1:
				return False
			stack.pop()

		elif sop.op == OP_DUP:
			if len(stack) < 1:
				return False
			v = stack[-1]
			stack.append(v)

		elif sop.op == OP_EQUAL or sop.op == OP_EQUALVERIFY:
			if len(stack) < 2:
				return False
			v1 = stack.pop()
			v2 = stack.pop()

			is_equal = (v1 == v2)
			if is_equal:
				stack.append("\x01")
			else:
				stack.append("\x00")

			if sop.op == OP_EQUALVERIFY:
				if is_equal:
					stack.pop()
				else:
					return False

		elif sop.op == OP_HASH160:
			if len(stack) < 1:
				return False
			stack.append(ser_uint160(Hash160(stack.pop())))

		elif sop.op == OP_NOP or (sop.op >= OP_NOP1 and sop.op <= OP_NOP10):
			pass

		elif sop.op == OP_RETURN:
			return False

		elif sop.op == OP_SHA256:
			if len(stack) < 1:
				return False
			stack.append(SHA256.new(stack.pop()).digest())

		elif sop.op == OP_VERIFY:
			if len(stack) < 1:
				return False
			v = CastToBool(stack[-1])
			if v:
				stack.pop()
			else:
				return False

		elif sop.op == OP_WITHIN:
			if len(stack) < 3:
				return False
			bn3 = CastToBigNum(stack.pop())
			bn2 = CastToBigNum(stack.pop())
			bn1 = CastToBigNum(stack.pop())
			v = (bn2 <= bn1) and (bn1 < bn3)
			if v:
				stack.append("\x01")
			else:
				stack.append("\x00")

		else:
			print "Unsupported opcode", OPCODE_NAMES[sop.op]
			return False

	return True

def CastToBigNum(s):
	v = vch2bn(s)
	return bn2vch(v)

def CastToBool(s):
	for i in xrange(len(s)):
		sv = ord(s[i])
		if sv != 0:
			if (i == (len(s) - 1)) and (sv == 0x80):
				return False
			return True

	return False

def VerifyScript(scriptSig, scriptPubKey, txTo, inIdx, hashtype):
	stack = []
	if not EvalScript(stack, scriptSig, txTo, inIdx, hashtype):
		return False
	if not EvalScript(stack, scriptPubKey, txTo, inIdx, hashtype):
		return False
	if len(stack) == 0:
		return False
	return CastToBool(stack[-1])

def VerifySignature(txFrom, txTo, inIdx, hashtype):
	if inIdx >= len(txTo.vin):
		return False
	txin = txTo.vin[inIdx]

	if txin.prevout.n >= len(txFrom.vout):
		return False
	txout = txFrom.vout[txin.prevout.n]

	txFrom.calc_sha256()

	if txin.prevout.hash != txFrom.sha256:
		return False

	if not VerifyScript(txin.scriptSig, txout.scriptPubKey, txTo, inIdx,
			    hashtype):
		return False

	return True




