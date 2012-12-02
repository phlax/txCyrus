import re

from twisted.internet import protocol
from twisted.internet import ssl
from twisted.mail import imap4
from twisted.python import log

re_q0  = re.compile(r'(.*)\s\(\)')
re_q   = re.compile(r'(.*)\s\(STORAGE (\d+) (\d+)\)')

class CyrusCommand(imap4.Command):
    _1_RESPONSES = (
        'CAPABILITY', 'FLAGS', 'LIST', 'LSUB', 'ACL', 'QUOTA', 'OK',
        'STATUS', 'SEARCH', 'NAMESPACE', 'GETACL', 'LQ')


class CyrusClient(imap4.IMAP4Client):
    """
    A client with callbacks for greeting messages from an IMAP server.
    """
    greetDeferred = None

    def serverGreeting(self, caps):
        self.serverCapabilities = caps
        if self.greetDeferred is not None:
            d, self.greetDeferred = self.greetDeferred, None
            d.callback(self)

    def list(self, reference, wildcard):
        """List a subset of the available mailboxes

        This command is allowed in the Authenticated and Selected states.

        @type reference: C{str}
        @param reference: The context in which to interpret C{wildcard}

        @type wildcard: C{str}
        @param wildcard: The pattern of mailbox names to match, optionally
        including either or both of the '*' and '%' wildcards.  '*' will
        match zero or more characters and cross hierarchical boundaries.
        '%' will also match zero or more characters, but is limited to a
        single hierarchical level.

        @rtype: C{Deferred}
        @return: A deferred whose callback is invoked with a list of C{tuple}s,
        the first element of which is a C{tuple} of mailbox flags, the second
        element of which is the hierarchy delimiter for this mailbox, and the
        third of which is the mailbox name; if the command is unsuccessful,
        the deferred's errback is invoked instead.
        """
        cmd = 'LIST'
        args = '"%s" "%s"' % (reference, wildcard.encode('imap4-utf-7'))
        resp = ('LIST',)
        command = imap4.Command(cmd, args, wantResponse=resp)
        d = self.sendCommand(command)
        d.addCallback(self.__cbList, 'LIST')
        return d

    lm = list

    def __cbList(self, (lines, last), command):
        results = []
        for parts in lines:
            if len(parts) == 4 and parts[0] == command:
                parts[1] = tuple(parts[1])
                results.append(tuple(parts[1:]))
        return results

    def lam(self, mailbox):
        cmd = 'GETACL'
        args = '"%s"' % (mailbox.encode('imap4-utf-7'))
        resp = ('ACL',)
        command = CyrusCommand(cmd, args, wantResponse=resp)
        d = self.sendCommand(command)
        d.addCallback(self.__cbGetacl, 'ACL')
        return d

    def __cbGetacl(self, (lines, last), command):
        results = []
        for parts in lines:
            cmd = parts.pop(0)
            mailbox = parts.pop(0)
            if cmd == command:
                [results.append(perm)
                 for perm in
                 zip(*(iter(parts), ) * 2)]
        return results


    def lq(self, mailbox):
        cmd = 'GETQUOTA'
        args = '"%s"' % (mailbox.encode('imap4-utf-7'))
        resp = ('QUOTA',)
        command = CyrusCommand(cmd, args, wantResponse=resp)
        d = self.sendCommand(command)
        d.addCallback(self.__cbLq, 'QUOTA').addErrback(self.__ebLq)
        return d

    def __ebLq(self, reason):
        if reason.getErrorMessage() == 'Quota root does not exist':
            return None

    def __cbLq(self, (lines, last), command):
        results = []
        for parts in lines:
            if len(parts) == 3 and parts[0] == command:
                results.append(tuple(parts[1:]))
        return results

    def _extraInfo(self, lines):
        # XXX - This is terrible.
        # XXX - Also, this should collapse temporally proximate calls into single
        #       invocations of IMailboxListener methods, where possible.
        flags = {}
        recent = exists = None
        for response in lines:
            elements = len(response)
            if elements == 1 and response[0] == ['READ-ONLY']:
                self.modeChanged(False)
            elif elements == 1 and response[0] == ['READ-WRITE']:
                self.modeChanged(True)
            elif elements == 2 and response[1] == 'EXISTS':
                exists = int(response[0])
            elif elements == 2 and response[1] == 'RECENT':
                recent = int(response[0])
            elif elements == 3 and response[1] == 'FETCH':
                mId = int(response[0])
                values = self._parseFetchPairs(response[2])
                flags.setdefault(mId, []).extend(values.get('FLAGS', ()))
            else:
                log.msg('Unhandled unsolicited response: %s' % (response,))

        if flags:
            self.flagsChanged(flags)
        if recent is not None or exists is not None:
            self.newMessages(exists, recent)

    def cm(self, mailbox, partition=None):
        cmd = 'CREATE'
        args = '"%s"' % (mailbox.encode('imap4-utf-7'))
        resp = ('CREATE',)
        command = CyrusCommand(cmd, args, wantResponse=resp)
        d = self.sendCommand(command)
        d.addCallback(self.__cbCreate, 'CREATE', mailbox)
        return d

    def __cbCreate(self, (lines, last), command, mailbox):
        if last == 'OK Completed':
            return True

    def dm(self, mailbox, recursive=True, unlock=True):
        def _dm(result):
            if result:
                return self.__dm(mailbox)

        if unlock:
            return self.sam(
                mailbox, 'cyrus', 'c').addCallback(_dm)
        return _dm(True)

    def __dm(self, mailbox):
        cmd = 'DELETE'
        args = '"%s"' % (mailbox.encode('imap4-utf-7'))
        resp = ('DELETE',)
        command = CyrusCommand(cmd, args, wantResponse=resp)
        d = self.sendCommand(command)
        d.addCallback(self.__cbDelete, 'DELETE', mailbox)
        return d

    def __cbDelete(self, (lines, last), command, mailbox):
        if last == 'OK Completed':
            return True

    def sam(self, mailbox, userid, rights):
        cmd = 'SETACL'
        args = '"%s" %s %s' % (
            mailbox.encode('imap4-utf-7'),
            userid,
            rights)
        resp = ('SETACL',)
        command = CyrusCommand(cmd, str(args), wantResponse=resp)
        d = self.sendCommand(command)
        d.addCallback(self.__cbSetacl, 'SETACL', mailbox)
        return d

    def __cbSetacl(self, (lines, last), command, mailbox):
        if last == 'OK Completed':
            return True


class CyrusClientFactory(protocol.ReconnectingClientFactory):
    usedUp = False
    protocol = CyrusClient

    def __init__(self, username, onConn):
        self.ctx = ssl.ClientContextFactory()
        self.username = username
        self.onConn = onConn

    def buildProtocol(self, addr):
        """
        Initiate the protocol instance. Since we are building a simple IMAP
        client, we don't bother checking what capabilities the server has. We
        just add all the authenticators twisted.mail has.  Note: Gmail no
        longer uses any of the methods below, it's been using XOAUTH since
        2010.
        """
        assert not self.usedUp
        self.usedUp = True
        p = self.protocol(self.ctx)
        p.factory = self
        p.greetDeferred = self.onConn
        p.registerAuthenticator(imap4.PLAINAuthenticator(self.username))
        p.registerAuthenticator(imap4.LOGINAuthenticator(self.username))
        p.registerAuthenticator(
            imap4.CramMD5ClientAuthenticator(self.username))
        return p

    def clientConnectionFailed(self, connector, reason):
        d, self.onConn = self.onConn, None
        d.errback(reason)
