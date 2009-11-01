#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Interface with rrdtool to generate appropriate postfix graph
statistics sent, recv, bounced, rejected messages are tracked.
"""
import sys, os, re, time
import rrdtool
import pdb
from optparse import OptionParser
from django.conf import settings

rrdstep           = 60
xpoints           = 540
points_per_sample = 3
rrd_inited        = False
this_minute       = 0

months_map = {
    'Jan' : 0, 'Feb' : 1, 'Mar' : 2,
    'Apr' : 3, 'May' : 4, 'Jun' : 5,
    'Jul' : 6, 'Aug' : 7, 'Sep' : 8,
    'Oct' : 9, 'Nov' :10, 'Dec' :11,
    'jan' : 0, 'feb' : 1, 'mar' : 2,
    'apr' : 3, 'may' : 4, 'jun' : 5,
    'jul' : 6, 'aug' : 7, 'sep' : 8,
    'oct' : 9, 'nov' :10, 'dec' :11,
}

def str2Time(y,M,d,h,m,s):
    """str2Time

    return epoch time from Year Month Day Hour:Minute:Second time format
    """
    try:
        local = time.strptime("%s %s %s %s:%s:%s" %(y,M,d,h,m,s), \
                          "%Y %b %d %H:%M:%S")
    except:
        print "[rrd] ERROR unrecognized %s time format" %(y,M,d,h,m,s)
        exit(0)
    return int(time.mktime(local))


class LogParser():
    """LogParser

    Parse a mail log in syslog format:
    Month day HH:MM:SS host prog[pid]: log message...

    For each epoch record the parser stores number of
    'sent', 'received', 'bounced','rejected' messages over
    a rrdstep period of time.

    parameters : logfile, and starting year
    
    """
    def __init__(self, logfile, rrd_rootdir, img_rootdir,
                 year=None, debug=False, verbose=False, graph=None):
        """constructor
        """
        self.logfile = logfile
        try:
            self.f = open(logfile)
        except IOError:
            sys.exit(1)
#         except (IOError, errno, strerror):
#             print "[rrd] I/O error({0}): {1} ".format(errno, strerror)+logfile
#             return None
        self.enable_year_decrement = None
        self.logfile = logfile
        self.rrd_rootdir = rrd_rootdir
        self.img_rootdir = img_rootdir
        self.year = year
        self.debug = debug
        self.verbose = verbose
        self.types = ['AVERAGE','MAX']
        self.natures = ['sent_recv','boun_reje']
        self.legend = {'sent_recv' : ['sent messages','received messages'],
                       'boun_reje' : ['bounced messages','rejected messages']}
        try:
            self.f = open(logfile)
        except IOError:
            sys.exit(1)
#         except (IOError, errno, strerror):
#             print "I/O error({0}): {1} ".format(errno, strerror)+logfile
#             sys.exit(1)

        self.data = {}
        self.last_month = None
        if not self.year:
            self.year = time.localtime().tm_year
        self.last_minute  = 0
        self.domains = ["ngyn.org", "streamcore.com"]
        for dom in self.domains:
            self.data[dom] = {}
                
        self.line_expr = re.compile("(\w+)\s+(\d+)\s+(\d+):(\d+):(\d+)\s+(\w+)\s+(\w+)/?\w*[[](\d+)[]]:\s+(.*)")
        self.workdict = {}
        self.process_log()

    def year_increment(self,month):
        """year_increment
        """
        if month == 0:
            if self.last_month and self.last_month == 1:
                self.year += 1
                self.enable_year_decrement = True
        elif month == 11:
            if self.enable_year_decrement \
               and self.last_month and self.last_month != 1:
                self.year -= 1
        else:
            self.enable_year_decrement = False

        self.last_month = month

    def process_line(self,text):
        """process_line

        Parse a log line and look for
        'sent','received','bounced',rejected' messages event

        Return True if data are up-to-date else False
        """
        # get date
        ret = False
        m = self.line_expr.match(text)
        if not m:
            return ret

        (mo, da, ho, mi, se, host, prog, pid, log) = m.groups()

        self.year_increment(months_map[mo])
        se = int(int(se) / rrdstep)            # rrd step is one-minute => se = 0
        cur_t = str2Time(self.year, mo, da, ho, mi, se)
        cur_t = cur_t - cur_t % rrdstep

        # watch events
        m = re.search("postfix\/qmgr.+(\w{10}): from=<(.*)>", text)
        if m:
            self.workdict[m.group(1)] = {'from' : m.group(2)}
            return True

        m = re.search("(\w{10}): to=<(.*)>.*status=(\S+)", text)
        if m:
            if not self.workdict.has_key(m.group(1)):
                print "Inconsistent mail, skipping"
                return False
            
            addrfrom = re.match("([^@]+)@(.+)", self.workdict[m.group(1)]['from'])
            if addrfrom and addrfrom.group(2) in self.domains:
                if not self.data[addrfrom.group(2)].has_key(cur_t):
                    self.data[addrfrom.group(2)][cur_t] = \
                        {'sent' : 0, 'recv' : 0, 'bounced' : 0, 'reje' : 0}
                self.data[addrfrom.group(2)][cur_t]['sent'] += 1
            addrto = re.match("([^@]+)@(.+)", m.group(2))
            if addrto.group(2) in self.domains:
                if not self.data[addrto.group(2)].has_key(cur_t):
                    self.data[addrto.group(2)][cur_t] = \
                        {'sent' : 0, 'recv' : 0, 'bounced' : 0, 'reje' : 0}
                if m.group(3) == "sent":
                    self.data[addrto.group(2)][cur_t]['recv'] += 1
                else:
                    self.data[addrto.group(2)][cur_t][m.group(3)] += 1
            return True
        
#         elif re.match(".*[0-9A-Z]+: client=(\S+).*",text):
#             self.data[cur_t]['recv'] += 1

#         elif re.match(".*(?:[0-9A-Z]+: |NOQUEUE: )?reject: .*",text):
#             self.data[cur_t]['reje'] += 1

#         elif re.match(".*(?:[0-9A-Z]+: |NOQUEUE: )?milter-reject: .*",text):
#             if not re.match(".*Blocked by SpamAssassin.*",text):
#                 self.data[cur_t]['reje'] += 1
            #else regiter spam

        return True

    def init_rrd(self, fname, m):
        """init_rrd

        Set-up Data Sources (DS)
        Set-up Round Robin Archives (RRA):
        - day,week,month and year archives
        - 2 types : AVERAGE and MAX

        parameter : start time
        return    : last epoch recorded
        """
        ds_type = 'ABSOLUTE'
        rows = xpoints / points_per_sample
        realrows = int(rows * 1.1)    # ensure that the full range is covered
        day_steps = int(3600 * 24 / (rrdstep * rows))
        week_steps = day_steps * 7
        month_steps = week_steps * 5
        year_steps = month_steps * 12

        # Set up data sources for our RRD
        params = []
        for v in ["sent", "recv", "bounced", "reje"]:
            params += ['DS:%s:%s:%s:0:U' % (v, ds_type, rrdstep * 2)]

        # Set up RRD to archive data
        rras = []
        for cf in ['AVERAGE', 'MAX']:
            for step in [day_steps, month_steps, month_steps, year_steps]:
                params += ['RRA:%s:0.5:%s:%s' % (cf, step, realrows)]

        # With those setup, we can now created the RRD
        if not os.path.exists(fname):
            rrdtool.create(fname,
                           '--start',str(m),
                           '--step',str(rrdstep),
                           *params)
            this_minute = m
        else:
            this_minute = rrdtool.last(fname) + rrdstep

        return this_minute


    def update_rrd(self, dom, t):
        """update_rrd

        Update RRD with records at t time.

        True  : if data are up-to-date for current minute
        False : syslog may have probably been already recorded
        or something wrong
        """
        fname = "%s/%s.rrd" % (self.rrd_rootdir, dom)
        m = t - (t % rrdstep)
        if not os.path.exists(fname):
            self.last_minute = self.init_rrd(fname, m)
            print "[rrd] create new RRD file"

        if m < self.last_minute:
            if self.verbose:
                print "[rrd] VERBOSE events at %s already recorded in RRD" %m
            return False
        if m == self.last_minute:
            return True

        # Missing some RRD steps
        if m > self.last_minute + rrdstep:
            for p in range(self.last_minute + rrdstep, m, rrdstep):
                if self.verbose:
                    print "[rrd] VERBOSE update %s:%s:%s:%s:%s (SKIP)" \
                          %(p,'0','0','0','0')
                rrdtool.update(fname, "%s:%s:%s:%s:%s" \
                                   % (p, '0', '0', '0', '0'))

        if self.verbose:
            print "[rrd] VERBOSE update %s:%s:%s:%s:%s" \
                  %(m,self.data[m]['sent'], self.data[m]['recv'],\
                    self.data[m]['boun'], self.data[m]['reje'])

        rrdtool.update(fname, "%s:%s:%s:%s:%s" \
                           % (m, self.data[dom][m]['sent'], self.data[dom][m]['recv'],\
                                  self.data[dom][m]['bounced'], self.data[dom][m]['reje']))
        self.last_minute = m
        return True

    def process_log(self):
        """process_log

        Go through entire log file
        """
        for line in self.f.readlines():
            evt = self.process_line(line)

        # Sort everything by time
        for dom, data in self.data.iteritems():
            sortedData = {}
            sortedData = [ (i, data[i]) for i in sorted(data.keys()) ]
            for t, dict in sortedData:
                if self.update_rrd(dom, t):
                    if not self.first_minute:
                        self.first_minute = t
                    self.last_minute = t

    def newgraph(self, target="global", color1 = "#990033", color2 = "#330099",
                 year = None, start = None, end = None, t =None, n = None):
        rrdfile = "%s/%s.rrd" % (self.rrd_rootdir, target)
        path = "%s/%s" % (self.img_rootdir, target)
        ext = "png"
        start = str(self.first_minute)
        end = str(self.last_minute)
        cfs = t and [t] or self.types
        ds1 = "sent"
        ds2 = "recv"
        for cf in cfs:
            fname = '%s_%s.%s' % (path, cf, ext)
            rrdtool.graph(fname,
                          '--imgformat', 'PNG',
                          '--width', '540',
                          '--height', '100',
                          '--start', str(start),
                          '--end', str(end),
                          '--vertical-label', '%s message' % cf.lower(),
                          '--title', '%s message flow per minute' % cf.lower(),
                          '--lower-limit', '0',
                          'DEF:%s=%s:%s:%s:' % (ds1, rrdfile, ds1, cf),
                          'DEF:%s=%s:%s:%s:' % (ds2, rrdfile, ds2, cf),
                          'LINE:%s%s:%s' % (ds1, color1, 'sent messages'),
                          'LINE:%s%s:%s' % (ds2, color2, 'receive messages')
                          )

    def plot_rrd(self, f=None, color1 = "#990033", color2 = "#330099",
                 year=None, start=None, end=None, t=None, n=None):
        """plot_rrd

        Graph rrd from start to end epoch
        """
        if f:
            self.imgFile = f
        start = str(self.first_minute)
        end   = str(self.last_minute)
        if t:
            self.types = t
        if n:
            self.natures = n

        if self.graph:
            try:
                start = int(time.mktime(time.strptime(self.graph[0], \
                                                      "%Y %b %d %H:%M:%S")))
                end = int(time.mktime(time.strptime(self.graph[1], \
                                                      "%Y %b %d %H:%M:%S")))
            except:
                print "[rrd] ERROR bad time format for option --graph"


        print "[rrd] plot rrd graph from %s to %s" \
              %(time.asctime(time.localtime(float(start))),\
                time.asctime(time.localtime(float(end))))
        if not year: year = time.localtime().tm_year
        self.imgFile
        if not os.path.exists(tmp_path):
            os.mkdir(tmp_path)
        for n in self.natures:
            for t in self.types:
                path = '%s%s_%s_%s'%(tmp_path,n,t,os.path.basename(self.imgFile))
                ds1 = n.split('_')[0]
                ds2 = n.split('_')[1]

                rrdtool.graph(
                    path,
                    '--imgformat','PNG',
                    '--width','540',
                    '--height','100',
                    '--start', str(start),
                    '--end', str(end),
                    '--vertical-label', '%s message' %t.lower(),
                    '--title', '%s message flow per minute' %t.lower(),
                    '--lower-limit', '0',
                    'DEF:%s=%s:%s:%s:' %(ds1,self.rrdfile,ds1,t),
                    'DEF:%s=%s:%s:%s:' %(ds2,self.rrdfile,ds2,t),
                    'LINE:%s%s:%s' %(ds1,color1,self.legend[n][0]),
                    'LINE:%s%s:%s' %(ds2,color2,self.legend[n][1])
                    )

def getoption(name, default=None):
    res = None
    try:
        res = getattr(settings, name)
    except AttributeError:
        res = default
    return res

if __name__ == "__main__":
    log_file = getoption("LOGFILE", "/var/log/maillog")
    rrd_rootdir = getoption("RRD_ROOTDIR", "/tmp")
    img_rootdir = getoption("IMG_ROOTDIR", "/tmp")

    parser = OptionParser()
    parser.add_option("-t", "--target", default="all",
                      help="Specify which target handled while parsing log file (default to all)")
    parser.add_option("-g","--graph", nargs=2, dest="graph",
                      help="generate graph in between time period (y M d YY:MM:SS)", 
                      metavar="START STOP")
    parser.add_option("-l","--logFile", default=log_file,
                      help="postfix log in syslog format", metavar="FILE")
    parser.add_option("-v","--verbose", default=False, action="store_true", 
                      dest="verbose", help="set verbose mode")
    parser.add_option("-d","--debug", default=False, action="store_true", 
                      dest="debug", help="set debug mode")
    (options, args) = parser.parse_args()
  
    P = LogParser(options.logFile, rrd_rootdir, img_rootdir,
                  debug=options.debug, verbose=options.verbose,
                  graph=options.graph)
    P.newgraph("streamcore.com")