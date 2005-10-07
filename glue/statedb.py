"""
The statedb module is the interface between the segment publishing script
and the metadata database.

$Id$
"""
import os
import socket
import pwd
import sys
import re
import time
import random
import exceptions
from glue import gpstime
import mx.ODBC.DB2

class StateSegmentDatabaseException(exceptions.Exception):
  """
  Exceptions raised by the classes and methods in this module
  will be instances of this class.
  """
  def __init__(self, args=None):
    """
    Create an instance of this class, ie. a StateSegmentDatabaseException
    exception.

    @param args: 

    @return: Instance of class StateSegmentDatabaseException
    """
    self.args = args


class StateSegmentDatabaseSegmentExistsException(exceptions.Exception):
  """
  Exceptions raised by the classes and methods in this module
  will be instances of this class.
  """
  def __init__(self, args=None):
    """
    Create an instance of this class, ie. a StateSegmentDatabaseException
    exception.

    @param args: 

    @return: Instance of class StateSegmentDatabaseException
    """
    self.args = args


class StateSegmentDatabase:
  """
  Class that represents an instance of a state segment database
  """
  def __init__(self, dbname, dbuser = '', dbpasswd = '', debug = False):
    """
    Open a connection to the state segment database.

    @param dbname: the name of the database containing the segments
    @type dbname: string
  
    @param username: the username which has permission to write to 
      the state segment database
    @type username: string

    @param passwd: the password of the user who has permission to write
      to the state segment database (optional)
    @type username: string
    """
    self.debug = debug
    self.db = None
    self.cursor = None
    self.state_vec = {}
    self.state_vec['H1'] = {}
    self.state_vec['H2'] = {}
    self.state_vec['L1'] = {}
    self.lfn_id = None
    self.framereg = re.compile(r'^([A-Za-z]+)\-(\w+)\-(\d+)\-(\d+)\.gwf$')
    self.process_id = None

    # seed the random number generator with the current time
    random.seed()

    # connect to the database
    try:
      self.db = mx.ODBC.DB2.Connect(dbname)
      self.cursor = self.db.cursor()
    except Exception, e:
      msg = "Error connecting to database: %s" % e
      raise StateSegmentDatabaseException, e

    # generate a process table for this instance of the publisher
    try:
      cvs_date = time.strptime( '$Date$'[7:-2], '%Y/%m/%d %H:%M:%S' )

      sql = "VALUES GENERATE_UNIQUE()"
      self.cursor.execute(sql)
      self.db.commit()
      self.process_id = self.cursor.fetchone()[0]

      process_tuple = ( os.path.basename(sys.argv[0]), 
        '$Revision$'[11:-2], 
        '$Source$' [9:-2],
        gpstime.GpsSecondsFromPyUTC( time.mktime(cvs_date) ),
        1,
        socket.gethostname(),
        pwd.getpwuid(os.geteuid())[0],
        os.getpid(),
        gpstime.GpsSecondsFromPyUTC(time.time()),
        self.process_id )
    
      sql = ' '.join(["INSERT INTO process (program,version,cvs_repository,",
      "cvs_entry_time,is_online,node,username,unix_procid,start_time,",
      "process_id) VALUES (", ','.join(['?' for x in process_tuple]), ")" ])

      self.cursor.execute(sql,process_tuple)
      self.db.commit()
    except Exception, e:
      msg = "Could not initialize process table: %s" % e
      raise StateSegmentDatabaseException, e

    # build a dictionary of the state vector types
    sql = "SELECT ifos, state_vec_major, state_vec_minor, segment_def_id "
    sql += "FROM segment_definer WHERE state_vec_major IS NOT NULL "
    sql += "AND state_vec_minor IS NOT NULL"
    try:
      self.cursor.execute(sql)
      self.db.commit()
      result = self.cursor.fetchall()
    except Exception, e:
      msg = "Error fetching state vector values from database: %s" % e
      raise StateSegmentDatabaseException, e
    for r in result:
      self.state_vec[r[0].strip()][tuple([r[1],r[2]])] = r[3]

    if self.debug:
      print "DEBUG: current state known state vec types are: "
      print self.state_vec
     
      
  def __del__(self):
    try:
      self.close()
    except:
      pass
    try:
      del self.cursor
    except:
      pass
    try:
      del self.db
    except:
      pass

  def close(self):
    """
    Close the connection to the database.
    """
    try:
      now = gpstime.GpsSecondsFromPyUTC(time.time())
      sql = "UPDATE process SET (end_time) = (?) WHERE process_id = (?)" 
      self.cursor.execute(sql,(now, self.process_id))
      self.db.commit()
    except Exception, e:
      msg = "Error inserting end_time into database: %s" % e
      raise StateSegmentDatabaseException, msg
    try:
      self.cursor.close()
      self.db.close()
    except Exception, e:
      msg = "Error closing connection to database: %s" % e
      raise StateSegmentDatabaseException, msg
      

  def register_lfn(self,lfn,start=None,end=None):
    """
    Start publishing state information for a new logical file name

    @param lfn: logical file name of object containing state data
    @type lfn: string
    """
    self.lfn_id = None

    r = self.framereg.search(lfn)
    if not r:
      if not start or not end:
        msg = "File %s not a frame file. Start and end times must be given" % \
          lfn
        raise StateSegmentDatabaseException, msg
    else:
      start = long(self.framereg.search(lfn).group(3))
      end = long(self.framereg.search(lfn).group(3)) + \
        long(self.framereg.search(lfn).group(4))
    
    try:
      # get a unique id for this lfn
      sql = "VALUES GENERATE_UNIQUE()"
      self.cursor.execute(sql)
      self.lfn_id = self.cursor.fetchone()[0]
     
      sql = "INSERT INTO lfn (process_id,lfn_id,lfn,start_time,end_time) "
      sql += "values (?,?,?,?,?)"
      self.cursor.execute(sql,(self.process_id,self.lfn_id,lfn,start,end))
      self.db.commit()

    except mx.ODBC.DB2.InterfaceError, e:
      if e[1] == -803:
        sql = "SELECT lfn_id from lfn WHERE lfn = '%s'" % lfn
        self.cursor.execute(sql)
        self.db.commit()
        self.lfn_id = self.cursor.fetchone()[0]
      else:
        msg = "Unable to obtain unique id for LFN : %s : %s" % (lfn,e)
        raise StateSegmentDatabaseException, msg

    except Exception, e:
      msg = "Unable to create entry for LFN : %s : %s" % (lfn,e)
      raise StateSegmentDatabaseException, msg
    

  def publish_state(self, 
      ifo, start_time, start_time_ns, end_time, end_time_ns, ver, val ):
    """
    Publish a state segment for a state vector in the database
    """

    # check that we have an lfn registered
    if not self.lfn_id:
      msg = "No LFN registered to publish state information"
      raise StateSegmentDatabaseException, msg

    # see if we need a new state val or if we know it already
    if (ver, val) not in self.state_vec[ifo]:
      try:
        sql = "VALUES GENERATE_UNIQUE()"
        self.cursor.execute(sql)
        self.state_vec[ifo][(ver,val)] = self.cursor.fetchone()[0]

        sql = "INSERT INTO segment_definer (process_id,segment_def_id,ifos,"
        sql += "name,version,comment,state_vec_major,state_vec_minor) VALUES "
        sql += "(?,?,?,?,?,?,?,?)"

        self.cursor.execute(sql,(self.process_id, 
          self.state_vec[ifo][(ver,val)], ifo,
          'STATEVEC.%d.%d' % (ver, val), 0, 
          'Created automatically by StateSegmentDatabase', ver, val))
        self.db.commit()

      except mx.ODBC.DB2.InterfaceError, e:
        if e[1] == -803:
          try:
            # handle the race condition where someone just 
            # beat us to defining this segment type
            sql = "SELECT segment_def_id FROM segment_definer WHERE "
            sql += "ifos = '" + ifo + "' AND "
            sql += "state_vec_major = %d AND state_vec_minor = %d" % (ver,val)
            self.cursor.execute(sql)
            self.db.commit()
            self.state_vec[ifo][(ver,val)] = self.cursor.fetchone()[0]
          except Exception, e:
            msg = "Error handling segment_definer race condition: %s" % e
            raise StateSegmentDatabaseException, e
        else:
          raise

      except Exception, e:
        msg = "Error inserting new segment_definer: %s" % e
        raise StateSegmentDatabaseException, e

      if self.debug:
        print ("DEBUG: using new state vec type (%s,%d,%d), id = " % \
          (ifo,ver,val)), 
        print tuple([self.state_vec[ifo][(ver,val)]])

    sv_id = self.state_vec[ifo][(ver,val)]

    # generate a unique id for the segment we are going to insert
    sql = "VALUES GENERATE_UNIQUE()"
    self.cursor.execute(sql)
    segment_id = self.cursor.fetchone()[0]

    # insert the segment
    sql = "INSERT INTO state_segment (process_id,segment_id,segment_def_id,"
    sql += "start_time,start_time_ns,end_time,end_time_ns,lfn_id)"
    sql += "VALUES (?,?,?,?,?,?,?,?)"

    for attempt in range(4):
      try:
        self.cursor.execute(sql, (self.process_id,segment_id,sv_id,
          start_time,start_time_ns,end_time,end_time_ns,self.lfn_id))
        self.db.commit()
        break

      # catch a deadlock and re-try up to three times
      except mx.ODBC.DB2.InternalError, e:
        if e[1] == -911 and int(e[0]) == 40001:
          if attempt < 3:
            time.sleep(random.randrange(0,5,1))
          else:
            msg = "error inserting segment information : %s" % e
            raise StateSegmentDatabaseException, msg
        else:
          msg = "error inserting segment information : %s" % e
          raise StateSegmentDatabaseException, msg

      # catch a duplicate entry and thore the exists exception
      except mx.ODBC.DB2.InterfaceError, e:
        if e[1] == -438 and int(e[0]) == 70001:
          msg = "state_segment must be unique: %s" % e
          raise StateSegmentDatabaseSegmentExistsException, e
        else:
          msg = "error inserting segment information : %s" % e
          raise StateSegmentDatabaseException, msg

      # catch all other exceptions
      except Exception, e:
        msg = "error inserting segment information : %s" % e
        raise StateSegmentDatabaseException, msg

    if self.debug:
      print "DEBUG: inserted with segment_id "
      print tuple([segment_id])
