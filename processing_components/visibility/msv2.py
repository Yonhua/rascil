#
# MeasurementSets V2 Reference Codes Based on Python-casacore 
#

import os
import gc
import re
import glob
import math
import numpy
import shutil
import scipy
from datetime import datetime
from collections import OrderedDict

from data_models.memory_data_models import Visibility, BlockVisibility, Configuration

__version__ = '0.1'
__revision__ = '$Rev$'
__all__ = ['Ms', 'STOKES_CODES', 'NUMERIC_STOKES']

STOKES_CODES = {'I': 1, 'Q': 2, 'U': 3, 'V': 4,
                'RR': 5, 'RL': 6, 'LR': 7, 'LL': 8,
                'XX': 9, 'XY': 10, 'YX': 11, 'YY': 12}

NUMERIC_STOKES = {1: 'I', 2: 'Q', 3: 'U', 4: 'V',
                  5: 'RR', 6: 'RL', 7: 'LR', 8: 'LL',
                  9: 'XX', 10: 'XY', 11: 'YX', 12: 'YY'}


def merge_baseline(ant1, ant2, shift=16):
    """
    Merge two stand ID numbers into a single baseline using the specified bit
    shift size.
    """

    return (ant1 << shift) | ant2


def split_baseline(baseline, shift=16):
    """
    Given a baseline, split it into it consistent stand ID numbers.
    """

    part = 2 ** shift - 1
    return (baseline >> shift) & part, baseline & part

try:
    from casacore.tables import table, tableutil

    class Antenna(object):
        """
        Information describing the location and properties of an antenna.
        """

        def __init__(self, id, x, y, z, name='', bits=8):
            self.id = id
            self.x = x
            self.y = y
            self.z = z
            self.levels = bits
            self.name = name
            self.polA = {'Type': 'X', 'Angle': 0.0, 'Cal': [0.0, 0.0]}
            self.polB = {'Type': 'Y', 'Angle': 90.0, 'Cal': [0.0, 0.0]}

        def getName(self):
            if self.name == '':
                return str(id)
            else:
                return self.name

    class Frequency:
        """
        Information about the frequency setup used in the file.
        """

        def __init__(self, bandFreq, channelWidth, bandwidth):
            self.id = 1
            self.bandFreq = bandFreq
            self.chWidth = channelWidth
            self.totalBW = bandwidth
            self.sideBand = 1
            self.baseBand = 0

    class VISData(object):
        """
        One UV visibility data set for a given observation time.
        """
        def __init__(self, obstime, inttime, baselines, visibilities, weights=None, pol=STOKES_CODES['XX'], source='z'):
            self.obstime = obstime
            self.inttime = inttime
            self.baselines = baselines
            self.visibilities = visibilities
            self.weights = weights
            self.pol = pol
            self.source = source

        def __cmp__(self, y):
            """
            Function to sort the self.data list in order of time and then
            polarization code.
            TODO @Wangfeng, support order
            """

            sID = (self.obstime, abs(self.pol))
            yID = (y.obstime, abs(y.pol))

            if sID > yID:
                return 1
            elif sID < yID:
                return -1
            else:
                return 0

        def time(self):
            return self.obstime

        def get_uvw(self, HA, dec, obs):
            # Need rewrite: 1) calculate uvw from xyz and observatory
            #               2) Copy from ARL 

            Nbase = len(self.baselines)
            uvw = numpy.zeros((Nbase, 3), dtype=numpy.float32)

            # Phase center coordinates
            # Convert numbers to radians and, for HA, hours to degrees
            HA2 = HA * 15.0 * numpy.pi / 180
            dec2 = dec * numpy.pi / 180
            lat2 = obs.lat

            # Coordinate transformation matrices
            trans1 = numpy.matrix([[0, -numpy.sin(lat2), numpy.cos(lat2)],
                                    [1, 0, 0],
                                    [0, numpy.cos(lat2), numpy.sin(lat2)]])
            trans2 = numpy.matrix([[numpy.sin(HA2), numpy.cos(HA2), 0],
                                    [-numpy.sin(dec2) * numpy.cos(HA2), numpy.sin(dec2) * numpy.sin(HA2),
                                    numpy.cos(dec2)],
                                    [numpy.cos(dec2) * numpy.cos(HA2), -numpy.cos(dec2) * numpy.sin(HA2),
                                    numpy.sin(dec2)]])

            for i, (a1, a2) in enumerate(self.baselines):
                # Go from a east, north, up coordinate system to a celestial equation,
                # east, north celestial pole system
                xyzPrime = a1.stand - a2.stand
                xyz = trans1 * numpy.matrix([[xyzPrime[0]], [xyzPrime[1]], [xyzPrime[2]]])

                # Go from CE, east, NCP to u, v, w
                temp = trans2 * xyz
                uvw[i, :] = numpy.squeeze(temp) / (scipy.constants.c) #speedOfLight

            return uvw

        def argsort(self, mapper=None, shift=16):
            # For a real application, we have to consider the mapper of antenna name and ID
            # TODO @wangfeng
            packed = []
            for a1, a2 in self.baselines:
                if mapper is None:
                    s1, s2 = a1.stand.id, a2.stand.id
                else:
                    s1, s2 = mapper[a1.stand.id], mapper[a2.stand.id]
                packed.append(merge_baseline(s1, s2, shift=shift))
            packed = numpy.array(packed, dtype=numpy.int32)

            return numpy.argsort(packed)

    class MS_UVData(VISData):
        """
        One MS UV visibility data set for a given observation time.
        """

        def get_uvw(self, HA, dec, obs):
            
            # Simple example, just for testing
            # Set all uvw=1

            Nbase = len(self.baselines)
            uvw = numpy.ones((Nbase, 3), dtype=numpy.float32)
            return uvw

        def argsort(self, mapper=None, shift=16):
            packed = []
            for a1, a2 in self.baselines:
                # if mapper is None:
                #     s1, s2 = a1.stand.id, a2.stand.id
                # else:
                #     s1, s2 = mapper.index(a1.stand.id), mapper.index(a2.stand.id)
                packed.append(merge_baseline(a1, a2, shift=shift))
            packed = numpy.array(packed, dtype=numpy.int32)

            return numpy.argsort(packed)

    class BaseData(object):
        """
        Base Data class: For an observation of interferometer, we should have:
        Antenna, Frequency, Visibility Funcdation, UVW
        """

        _MAX_ANTS = 255
        _PACKING_BIT_SHIFT = 8
        _STOKES_CODES = STOKES_CODES

        def parse_time(self, ref_time):
            """
            Given a time as either a integer, float, string, or datetime object,
            convert it to a string in the formation 'YYYY-MM-DDTHH:MM:SS'.
            """

            # Valid time string (modulo the 'T')
            timeRE = re.compile(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?')

            if type(ref_time) in (int, float):
                refDateTime = datetime.utcfromtimestamp(ref_time)
                ref_time = refDateTime.strftime("%Y-%m-%dT%H:%M:%S")
            elif type(ref_time) == datetime:
                ref_time = ref_time.strftime("%Y-%m-%dT%H:%M:%S")
            elif type(ref_time) == str:
                # Make sure that the string times are of the correct format
                if re.match(timeRE, ref_time) is None:
                    raise RuntimeError("Malformed date/time provided: %s" % ref_time)
                else:
                    ref_time = ref_time.replace(' ', 'T', 1)
            else:
                raise RuntimeError("Unknown time format provided.")

            return ref_time

        def __init__(self, filename, ref_time=0.0, verbose=False):
            # File-specific information
            self.filename = filename
            self.verbose = verbose

            # Observatory-specific information
            self.siteName = 'Unknown'

            # Observation-specific information
            self.ref_time = self.parse_time(ref_time)
            self.nant = 0
            self.nchan = 0
            self.nstokes = 0
            self.refVal = 0
            self.refPix = 0
            self.channel_width = 0

            # Parameters that store the meta-data and data
            self.array = []
            self.freq = []
            self.stokes = []
            self.data = []

        def __enter__(self):
            return self

        def __exit__(self, type, value, tb):
            self.write()
            self.close()

        def set_stokes(self, polList):
            """
            Given a list of Stokes parameters, update the object's parameters.
            """

            for pol in polList:
                if type(pol) == str:
                    numericPol = self._STOKES_CODES[pol.upper()]
                else:
                    numericPol = pol

                if numericPol not in self.stokes:
                    self.stokes.append(numericPol)

            # Sort into order of 'XX', 'YY', 'XY', and 'YX' or 'I', 'Q', 'U', and 'V'
            self.stokes.sort()
            if self.stokes[0] < 0:
                self.stokes.reverse()

            self.nStokes = len(self.stokes)

        def set_frequency(self, freq):
            """
            Given a numpy array of frequencies, set the relevant common observation
            parameters and add an entry to the self.freq list.
            """

            if self.nchan == 0:
                self.nchan = len(freq)
                self.refVal = freq[0]
                self.refPix = 1
                self.channelWidth = numpy.abs(freq[1] - freq[0])
                offset = 0.0
            else:
                assert (len(freq) == self.nchan)
                offset = freq[0] - self.refVal
            totalWidth = numpy.abs(freq[-1] - freq[0])

            freqSetup = Frequency(offset, self.channelWidth, totalWidth)
            self.freq.append(freqSetup)

        def set_geometry(self, *args, **kwds):
            """
            Given a station and an array of stands, set the relevant common observation
            parameters and add entries to the self.array list.
            """

            raise NotImplementedError

        def add_data_set(self, obstime, inttime, baselines, visibilities, weights=None, pol='XX', source='z'):
            """
            Create a UVData object to store a collection of visibilities.

            """

            if type(pol) == str:
                numericPol = self._STOKES_CODES[pol.upper()]
            else:
                numericPol = pol

            self.data.append(
                VISData(obstime, inttime, baselines, visibilities, weights=weights, pol=numericPol, source=source))

        def write(self):
            """
            Fill in the file will all of the required supporting metadata.
            """

            raise NotImplementedError

        def close(self):
            """
            Close out the file.
            """

            raise NotImplementedError

    class WriteMs(BaseData):
        """
        Class for storing visibility data and writing the data, along with array
        geometry, frequency setup, etc., to a CASA measurement set.
        """

        _STOKES_CODES = STOKES_CODES

        def __init__(self, filename, ref_time=0.0, verbose=False, memmap=None, ifdelete=False):
            """
            Initialize a new Measurement set object using a filename and a reference time
            given in seconds since the UNIX 1970 ephem, a python datetime object, or a
            string in the format of 'YYYY-MM-DDTHH:MM:SS'.
            """

            # Open the file and get going
            if os.path.exists(filename):
                if ifdelete:
                    shutil.rmtree(filename, ignore_errors=False)
                else:
                    raise IOError("File '%s' already exists" % filename)
            self.basename = filename

            # File-specific information
            super(WriteMs, self).__init__(filename, ref_time=ref_time, verbose=verbose)

        def set_geometry_arl(self, site_config, antennas, bits=8):
            """
            Given a station and an array of stands, set the relevant common observation
            parameters and add entries to the self.array list.

            configuration - base.py

            """

            # Update the observatory-specific information
            self.siteName = site_config.name

            stands = antennas

            arrayX, arrayY, arrayZ = 0,0,0

            xyz = site_config.xyz[:]

            # Create the stand mapper
            mapper = []
            ants = []
            for i in range(len(stands)):
                ants.append(Antenna(stands[i], xyz[i,0], xyz[i,1], xyz[i,2], bits=bits))
                mapper.append(stands[i])

            self.nant = len(ants)
            self.array.append({'center': [  arrayX, arrayY, arrayZ], 'ants': ants, 'mapper': mapper, 'inputAnts': antennas})


        def set_geometry(self, site_config, antennas, bits=8):
            """
            Given a station and an array of stands, set the relevant common observation
            parameters and add entries to the self.array list.

            configuration - base.py

            """

            # Update the observatory-specific information
            self.siteName = site_config.name

            stands = antennas

            arrayX, arrayY, arrayZ = 0,0,0

            xyz = site_config.xyz[:]

            # Create the stand mapper
            # No use if don't need to consider antenna name
            mapper = []
            ants = []
            for i in range(len(stands)):
                ants.append(Antenna(stands[i], xyz[i,0], xyz[i,1], xyz[i,2], bits=bits))
                mapper.append(stands[i])

            self.nant = len(ants)
            self.array.append({'center': [  arrayX, arrayY, arrayZ], 'ants': ants, 'mapper': mapper, 'inputAnts': antennas})

        def add_data_set(self, obstime, inttime, baselines, visibilities, pol='XX', source='z'):
            """
            Create a UVData object to store a collection of visibilities.
            """

            if type(pol) == str:
                numericPol = self._STOKES_CODES[pol.upper()]
            else:
                numericPol = pol

            self.data.append(MS_UVData(obstime, inttime, baselines, visibilities, pol=numericPol, source=source))

        def write(self):
            """
            Fill in the Measurement Sets file with correct order.
            """

            # Validate
            if self.nStokes == 0:
                raise RuntimeError("No polarization setups defined")
            if len(self.freq) == 0:
                raise RuntimeError("No frequency setups defined")
            if self.nant == 0:
                raise RuntimeError("No array geometry defined")
            if len(self.data) == 0:
                raise RuntimeError("No visibility data defined")

            # Sort the data set
            
            #self.data.sort()

            # Write the tables
            self._write_main_table()
            self._write_antenna_table()
            self._write_polarization_table()
            self._write_observation_table()
            self._write_spectralwindow_table()
            self._write_misc_required_tables()

            # Fixup the info and keywords for the main table
            tb = table("%s" % self.basename, readonly=False, ack=False)
            tb.putinfo({'type': 'Measurement Set',
                        'readme': 'This is a MeasurementSet Table holding measurements from a Telescope'})
            tb.putkeyword('MS_VERSION', numpy.float32(2.0))
            for filename in sorted(glob.glob('%s/*' % self.basename)):
                if os.path.isdir(filename):
                    tname = os.path.basename(filename)
                    stb = table("%s/%s" % (self.basename, tname), ack=False)
                    tb.putkeyword(tname, stb)
                    stb.close()
            tb.flush()
            tb.close()

            # Clear out the data section
            del (self.data[:])
            gc.collect()

        def close(self):
            """
            Close out the file.
            """

            pass

        def _write_antenna_table(self):
            """
            Write the antenna table.
            """

            col1 = tableutil.makearrcoldesc('OFFSET', 0.0, 1,
                                            comment='Axes offset of mount to FEED REFERENCE point',
                                            keywords={'QuantumUnits': ['m', 'm', 'm'],
                                                    'MEASINFO': {'type': 'position', 'Ref': 'ITRF'}
                                                    })
            col2 = tableutil.makearrcoldesc('POSITION', 0.0, 1,
                                            comment='Antenna X,Y,Z phase reference position',
                                            keywords={'QuantumUnits': ['m', 'm', 'm'],
                                                    'MEASINFO': {'type': 'position', 'Ref': 'ITRF'}
                                                    })
            col3 = tableutil.makescacoldesc('TYPE', "ground-based",
                                            comment='Antenna type (e.g. SPACE-BASED)')
            col4 = tableutil.makescacoldesc('DISH_DIAMETER', 2.0,
                                            comment='Physical diameter of dish',
                                            keywords={'QuantumUnits': ['m', ]})
            col5 = tableutil.makescacoldesc('FLAG_ROW', False,
                                            comment='Flag for this row')
            col6 = tableutil.makescacoldesc('MOUNT', "alt-az",
                                            comment='Mount type e.g. alt-az, equatorial, etc.')
            col7 = tableutil.makescacoldesc('NAME', "none",
                                            comment='Antenna name, e.g. VLA22, CA03')
            col8 = tableutil.makescacoldesc('STATION', self.siteName,
                                            comment='Station (antenna pad) name')

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8])
            tb = table("%s/ANTENNA" % self.basename, desc, nrow=self.nant, ack=False)

            tb.putcol('OFFSET', numpy.zeros((self.nant, 3)), 0, self.nant)
            tb.putcol('TYPE', ['GROUND-BASED,'] * self.nant, 0, self.nant)
            tb.putcol('DISH_DIAMETER', [2.0, ] * self.nant, 0, self.nant)
            tb.putcol('FLAG_ROW', [False, ] * self.nant, 0, self.nant)
            tb.putcol('MOUNT', ['ALT-AZ', ] * self.nant, 0, self.nant)
            tb.putcol('NAME', [ant.getName() for ant in self.array[0]['ants']], 0, self.nant)
            tb.putcol('STATION', [self.siteName, ] * self.nant, 0, self.nant)

            for i, ant in enumerate(self.array[0]['ants']):
                # tb.putcell('OFFSET', i, [0.0, 0.0, 0.0])
                tb.putcell('POSITION', i, [ant.x + self.array[0]['center'][0],
                                        ant.y + self.array[0]['center'][1],
                                        ant.z + self.array[0]['center'][2]])
                # tb.putcell('TYPE', i, 'GROUND-BASED')
                # tb.putcell('DISH_DIAMETER', i, 2.0)
                # tb.putcell('FLAG_ROW', i, False)
                # tb.putcell('MOUNT', i, 'ALT-AZ')
                # tb.putcell('NAME', i, ant.getName())
                # tb.putcell('STATION', i, self.siteName)

            tb.flush()
            tb.close()

        def _write_polarization_table(self):
            """
            Write the polarization table.
            """

            # Polarization

            stks = numpy.array(self.stokes)
            prds = numpy.zeros((2, self.nStokes), dtype=numpy.int32)
            for i, stk in enumerate(self.stokes):
                stks[i] = stk
                if stk > 4:
                    prds[0, i] = ((stk - 1) % 4) / 2
                    prds[1, i] = ((stk - 1) % 4) % 2
                else:
                    prds[0, i] = 1
                    prds[1, i] = 1

            col1 = tableutil.makearrcoldesc('CORR_TYPE', 0, 1,
                                            comment='The polarization type for each correlation product, as a Stokes enum.')
            col2 = tableutil.makearrcoldesc('CORR_PRODUCT', 0, 2,
                                            comment='Indices describing receptors of feed going into correlation')
            col3 = tableutil.makescacoldesc('FLAG_ROW', False,
                                            comment='flag')
            col4 = tableutil.makescacoldesc('NUM_CORR', self.nStokes,
                                            comment='Number of correlation products')

            desc = tableutil.maketabdesc([col1, col2, col3, col4])
            tb = table("%s/POLARIZATION" % self.basename, desc, nrow=1, ack=False)

            tb.putcell('CORR_TYPE', 0, self.stokes)
            tb.putcell('CORR_PRODUCT', 0, prds.T)
            tb.putcell('FLAG_ROW', 0, False)
            tb.putcell('NUM_CORR', 0, self.nStokes)

            tb.flush()
            tb.close()

            # Feed

            col1 = tableutil.makearrcoldesc('POSITION', 0.0, 1,
                                            comment='Position of feed relative to feed reference position',
                                            keywords={'QuantumUnits': ['m', 'm', 'm'],
                                                    'MEASINFO': {'type': 'position', 'Ref': 'ITRF'}
                                                    })
            col2 = tableutil.makearrcoldesc('BEAM_OFFSET', 0.0, 2,
                                            comment='Beam position offset (on sky but in antennareference frame)',
                                            keywords={'QuantumUnits': ['rad', 'rad'],
                                                    'MEASINFO': {'type': 'direction', 'Ref': 'J2000'}
                                                    })
            col3 = tableutil.makearrcoldesc('POLARIZATION_TYPE', 'X', 1,
                                            comment='Type of polarization to which a given RECEPTOR responds')
            col4 = tableutil.makearrcoldesc('POL_RESPONSE', 1j, 2,
                                            valuetype='complex',
                                            comment='D-matrix i.e. leakage between two receptors')
            col5 = tableutil.makearrcoldesc('RECEPTOR_ANGLE', 0.0, 1,
                                            comment='The reference angle for polarization',
                                            keywords={'QuantumUnits': ['rad', ]})
            col6 = tableutil.makescacoldesc('ANTENNA_ID', 0,
                                            comment='ID of antenna in this array')
            col7 = tableutil.makescacoldesc('BEAM_ID', -1,
                                            comment='Id for BEAM model')
            col8 = tableutil.makescacoldesc('FEED_ID', 0,
                                            comment='Feed id')
            col9 = tableutil.makescacoldesc('INTERVAL', 0.0,
                                            comment='Interval for which this set of parameters is accurate',
                                            keywords={'QuantumUnits': ['s', ]})
            col10 = tableutil.makescacoldesc('NUM_RECEPTORS', 2,
                                            comment='Number of receptors on this feed (probably 1 or 2)')
            col11 = tableutil.makescacoldesc('SPECTRAL_WINDOW_ID', -1,
                                            comment='ID for this spectral window setup')
            col12 = tableutil.makescacoldesc('TIME', 0.0,
                                            comment='Midpoint of time for which this set of parameters is accurate',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8,
                                        col9, col10, col11, col12])
            tb = table("%s/FEED" % self.basename, desc, nrow=self.nant, ack=False)

            presp = numpy.zeros((self.nant, 2, 2), dtype=numpy.complex64)
            if self.stokes[0] > 8:
                ptype = numpy.tile([b'X',b'Y'], (self.nant, 1))
                presp[:, 0, 0] = 1.0
                presp[:, 0, 1] = 0.0
                presp[:, 1, 0] = 0.0
                presp[:, 1, 1] = 1.0
            elif self.stokes[0] > 4:
                ptype = numpy.tile([b'R', b'L'], (self.nant, 1))
                presp[:, 0, 0] = 1.0
                presp[:, 0, 1] = -1.0j
                presp[:, 1, 0] = 1.0j
                presp[:, 1, 1] = 1.0
            else:
                ptype = numpy.tile([b'X', b'Y'], (self.nant, 1))
                presp[:, 0, 0] = 1.0
                presp[:, 0, 1] = 0.0
                presp[:, 1, 0] = 0.0
                presp[:, 1, 1] = 1.0

            tb.putcol('POSITION', numpy.zeros((self.nant, 3)), 0, self.nant)
            tb.putcol('BEAM_OFFSET', numpy.zeros((self.nant, 2, 2)), 0, self.nant)
            tb.putcol('POLARIZATION_TYPE', ptype, 0, self.nant)
            tb.putcol('POL_RESPONSE', presp, 0, self.nant)
            tb.putcol('RECEPTOR_ANGLE', numpy.zeros((self.nant, 2)), 0, self.nant)
            tb.putcol('ANTENNA_ID', list(range(self.nant)), 0, self.nant)
            tb.putcol('BEAM_ID', [-1, ] * self.nant, 0, self.nant)
            tb.putcol('FEED_ID', [0, ] * self.nant, 0, self.nant)
            tb.putcol('INTERVAL', [0.0, ] * self.nant, 0, self.nant)
            tb.putcol('NUM_RECEPTORS', [2, ] * self.nant, 0, self.nant)
            tb.putcol('SPECTRAL_WINDOW_ID', [-1, ] * self.nant, 0, self.nant)
            tb.putcol('TIME', [0.0, ] * self.nant, 0, self.nant)

            tb.flush()
            tb.close()

        def _write_observation_table(self):
            """
            Write the observation table.
            """

            # Observation

            col1 = tableutil.makearrcoldesc('TIME_RANGE', 0.0, 1,
                                            comment='Start and end of observation',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })
            col2 = tableutil.makearrcoldesc('LOG', 'none', 1,
                                            comment='Observing log')
            col3 = tableutil.makearrcoldesc('SCHEDULE', 'none', 1,
                                            comment='Observing schedule')
            col4 = tableutil.makescacoldesc('FLAG_ROW', False,
                                            comment='Row flag')
            col5 = tableutil.makescacoldesc('OBSERVER', 'ZASKY',
                                            comment='Name of observer(s)')
            col6 = tableutil.makescacoldesc('PROJECT', 'ZASKY',
                                            comment='Project identification string')
            col7 = tableutil.makescacoldesc('RELEASE_DATE', 0.0,
                                            comment='Release date when data becomes public',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })
            col8 = tableutil.makescacoldesc('SCHEDULE_TYPE', 'none',
                                            comment='Observing schedule type')
            col9 = tableutil.makescacoldesc('TELESCOPE_NAME', self.siteName,
                                            comment='Telescope Name (e.g. WSRT, VLBA)')

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8, col9])
            tb = table("%s/OBSERVATION" % self.basename, desc, nrow=1, ack=False)

            tStart = 0. 
            tStop = 0.5

            tb.putcell('TIME_RANGE', 0, [tStart * 86400, tStop * 86400])
            tb.putcell('LOG', 0, 'Not provided')
            tb.putcell('SCHEDULE', 0, 'Not provided')
            tb.putcell('FLAG_ROW', 0, False)
            tb.putcell('OBSERVER', 0, 'ZASKY')
            tb.putcell('PROJECT', 0, 'ZASKY')
            tb.putcell('RELEASE_DATE', 0, tStop * 86400)
            tb.putcell('SCHEDULE_TYPE', 0, 'None')
            tb.putcell('TELESCOPE_NAME', 0, self.siteName)

            tb.flush()
            tb.close()

            # Source
            # TODO @wangfeng
            #      We need to transfer the observatory information from ARL
            #         and replace the lat, lon, elev 
            arrayGeo = 110.
            arrayGeo = 21.

            # obs = ephem.Observer()
            # obs.lat = arrayGeo.lat * numpy.pi / 180
            # obs.lon = arrayGeo.lng * numpy.pi / 180
            # obs.elev = arrayGeo.elv * numpy.pi / 180
            # obs.pressure = 0

            nameList = []
            posList = []
            sourceID = 0
            for dataSet in self.data:
                if dataSet.pol == self.stokes[0]:
                    # TODO @wangfeng
                    #      observational time: utc
                    utc = 0 
                    # date = 
                    # date.hours = 0
                    # date.minutes = 0
                    # date.seconds = 0
                    utc0 = 2458485.0 # 2019.1.1

                    currSourceName = 'TEST' #dataSet.source.name

                    if currSourceName not in nameList:
                        sourceID += 1
                        ## Real-live sources (ephem.Body instances)
                        name = 'TEST'
                        equ = 0.
                        equPo = 0.                                            

                        # J2000 zenith equatorial coordinates
                        posList.append([0., 0.]) #equPo.ra * numpy.pi / 180, equPo.dec * numpy.pi / 180])

                        # name
                        nameList.append(name)

            nSource = len(nameList)

            # Save these for later since we might need them
            self._sourceTable = nameList

            col1 = tableutil.makearrcoldesc('DIRECTION', 0.0, 1,
                                            comment='Direction (e.g. RA, DEC).',
                                            keywords={'QuantumUnits': ['rad', 'rad'],
                                                    'MEASINFO': {'type': 'direction', 'Ref': 'J2000'}
                                                    })
            col2 = tableutil.makearrcoldesc('PROPER_MOTION', 0.0, 1,
                                            comment='Proper motion',
                                            keywords={'QuantumUnits': ['rad/s', ]})
            col3 = tableutil.makescacoldesc('CALIBRATION_GROUP', 0,
                                            comment='Number of grouping for calibration purpose.')
            col4 = tableutil.makescacoldesc('CODE', "none",
                                            comment='Special characteristics of source, e.g. Bandpass calibrator')
            col5 = tableutil.makescacoldesc('INTERVAL', 0.0,
                                            comment='Interval of time for which this set of parameters is accurate',
                                            keywords={'QuantumUnits': ['s', ]})
            col6 = tableutil.makescacoldesc('NAME', "none",
                                            comment='Name of source as given during observations')
            col7 = tableutil.makescacoldesc('NUM_LINES', 0,
                                            comment='Number of spectral lines')
            col8 = tableutil.makescacoldesc('SOURCE_ID', 0,
                                            comment='Source id')
            col9 = tableutil.makescacoldesc('SPECTRAL_WINDOW_ID', -1,
                                            comment='ID for this spectral window setup')
            col10 = tableutil.makescacoldesc('TIME', 0.0,
                                            comment='Midpoint of time for which this set of parameters is accurate.',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })
            col11 = tableutil.makearrcoldesc('TRANSITION', 'none', 1,
                                            comment='Line Transition name')
            col12 = tableutil.makearrcoldesc('REST_FREQUENCY', 1.0, 1,
                                            comment='Line rest frequency',
                                            keywords={'QuantumUnits': ['Hz', ],
                                                    'MEASINFO': {'type': 'frequency',
                                                                    'Ref': 'LSRK'}
                                                    })
            col13 = tableutil.makearrcoldesc('SYSVEL', 1.0, 1,
                                            comment='Systemic velocity at reference',
                                            keywords={'QuantumUnits': ['m/s', ],
                                                    'MEASINFO': {'type': 'radialvelocity',
                                                                    'Ref': 'LSRK'}
                                                    })

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8, col9,
                                        col10, col11, col12, col13])
            tb = table("%s/SOURCE" % self.basename, desc, nrow=nSource, ack=False)

            for i in range(nSource):
                tb.putcell('DIRECTION', i, posList[i])
                tb.putcell('PROPER_MOTION', i, [0.0, 0.0])
                tb.putcell('CALIBRATION_GROUP', i, 0)
                tb.putcell('CODE', i, 'none')
                tb.putcell('INTERVAL', i, 0.0)
                tb.putcell('NAME', i, nameList[i])
                tb.putcell('NUM_LINES', i, 0)
                tb.putcell('SOURCE_ID', i, i)
                tb.putcell('SPECTRAL_WINDOW_ID', i, -1)
                tb.putcell('TIME', i, (tStart + tStop) / 2 * 86400)
                # tb.putcell('TRANSITION', i, [])
                # tb.putcell('REST_FREQUENCY', i, [])
                # tb.putcell('SYSVEL', i, [])

            tb.flush()
            tb.close()

            # Field

            col1 = tableutil.makearrcoldesc('DELAY_DIR', 0.0, 2,
                                            comment='Direction of delay center (e.g. RA, DEC)as polynomial in time.',
                                            keywords={'QuantumUnits': ['rad', 'rad'],
                                                    'MEASINFO': {'type': 'direction', 'Ref': 'J2000'}
                                                    })
            col2 = tableutil.makearrcoldesc('PHASE_DIR', 0.0, 2,
                                            comment='Direction of phase center (e.g. RA, DEC).',
                                            keywords={'QuantumUnits': ['rad', 'rad'],
                                                    'MEASINFO': {'type': 'direction', 'Ref': 'J2000'}
                                                    })
            col3 = tableutil.makearrcoldesc('REFERENCE_DIR', 0.0, 2,
                                            comment='Direction of REFERENCE center (e.g. RA, DEC).as polynomial in time.',
                                            keywords={'QuantumUnits': ['rad', 'rad'],
                                                    'MEASINFO': {'type': 'direction', 'Ref': 'J2000'}
                                                    })
            col4 = tableutil.makescacoldesc('CODE', "none",
                                            comment='Special characteristics of field, e.g. Bandpass calibrator')
            col5 = tableutil.makescacoldesc('FLAG_ROW', False,
                                            comment='Row Flag')
            col6 = tableutil.makescacoldesc('NAME', "none",
                                            comment='Name of this field')
            col7 = tableutil.makescacoldesc('NUM_POLY', 0,
                                            comment='Polynomial order of _DIR columns')
            col8 = tableutil.makescacoldesc('SOURCE_ID', 0,
                                            comment='Source id')
            col9 = tableutil.makescacoldesc('TIME', (tStart + tStop) / 2,
                                            comment='Time origin for direction and rate',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8, col9])
            tb = table("%s/FIELD" % self.basename, desc, nrow=nSource, ack=False)

            for i in range(nSource):
                tb.putcell('DELAY_DIR', i, numpy.array([posList[i], ]))
                tb.putcell('PHASE_DIR', i, numpy.array([posList[i], ]))
                tb.putcell('REFERENCE_DIR', i, numpy.array([posList[i], ]))
                tb.putcell('CODE', i, 'None')
                tb.putcell('FLAG_ROW', i, False)
                tb.putcell('NAME', i, nameList[i])
                tb.putcell('NUM_POLY', i, 0)
                tb.putcell('SOURCE_ID', i, i)
                tb.putcell('TIME', i, (tStart + tStop) / 2 * 86400)

            tb.flush()
            tb.close()

        def _write_spectralwindow_table(self):
            """
            Write the spectral window table.
            """

            # Spectral Window

            nBand = len(self.freq)

            col1 = tableutil.makescacoldesc('MEAS_FREQ_REF', 0,
                                            comment='Frequency Measure reference')
            col2 = tableutil.makearrcoldesc('CHAN_FREQ', 0.0, 1,
                                            comment='Center frequencies for each channel in the data matrix',
                                            keywords={'QuantumUnits': ['Hz', ],
                                                    'MEASINFO': {'type': 'frequency',
                                                                'VarRefCol': 'MEAS_FREQ_REF',
                                                                'TabRefTypes': ['REST', 'LSRK', 'LSRD', 'BARY', 'GEO',
                                                                                'TOPO', 'GALACTO', 'LGROUP', 'CMB',
                                                                                'Undefined'],
                                                                'TabRefCodes': [0, 1, 2, 3, 4, 5, 6, 7, 8, 64]}
                                                    })
            col3 = tableutil.makescacoldesc('REF_FREQUENCY', self.refVal,
                                            comment='The reference frequency',
                                            keywords={'QuantumUnits': ['Hz', ],
                                                    'MEASINFO': {'type': 'frequency',
                                                                'VarRefCol': 'MEAS_FREQ_REF',
                                                                'TabRefTypes': ['REST', 'LSRK', 'LSRD', 'BARY', 'GEO',
                                                                                'TOPO', 'GALACTO', 'LGROUP', 'CMB',
                                                                                'Undefined'],
                                                                'TabRefCodes': [0, 1, 2, 3, 4, 5, 6, 7, 8, 64]}
                                                    })
            col4 = tableutil.makearrcoldesc('CHAN_WIDTH', 0.0, 1,
                                            comment='Channel width for each channel',
                                            keywords={'QuantumUnits': ['Hz', ]})
            col5 = tableutil.makearrcoldesc('EFFECTIVE_BW', 0.0, 1,
                                            comment='Effective noise bandwidth of each channel',
                                            keywords={'QuantumUnits': ['Hz', ]})
            col6 = tableutil.makearrcoldesc('RESOLUTION', 0.0, 1,
                                            comment='The effective noise bandwidth for each channel',
                                            keywords={'QuantumUnits': ['Hz', ]})
            col7 = tableutil.makescacoldesc('FLAG_ROW', False,
                                            comment='flag')
            col8 = tableutil.makescacoldesc('FREQ_GROUP', 1,
                                            comment='Frequency group')
            col9 = tableutil.makescacoldesc('FREQ_GROUP_NAME', "group1",
                                            comment='Frequency group name')
            col10 = tableutil.makescacoldesc('IF_CONV_CHAIN', 0,
                                            comment='The IF conversion chain number')
            col11 = tableutil.makescacoldesc('NAME', "%i channels" % self.nchan,
                                            comment='Spectral window name')
            col12 = tableutil.makescacoldesc('NET_SIDEBAND', 0,
                                            comment='Net sideband')
            col13 = tableutil.makescacoldesc('NUM_CHAN', 0,
                                            comment='Number of spectral channels')
            col14 = tableutil.makescacoldesc('TOTAL_BANDWIDTH', 0.0,
                                            comment='The total bandwidth for this window',
                                            keywords={'QuantumUnits': ['Hz', ]})

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8, col9,
                                        col10, col11, col12, col13, col14])
            tb = table("%s/SPECTRAL_WINDOW" % self.basename, desc, nrow=nBand, ack=False)

            for i, freq in enumerate(self.freq):
                tb.putcell('MEAS_FREQ_REF', i, 0)
                tb.putcell('CHAN_FREQ', i, self.refVal + freq.bandFreq + numpy.arange(self.nchan) * self.channelWidth)
                tb.putcell('REF_FREQUENCY', i, self.refVal)
                tb.putcell('CHAN_WIDTH', i, [freq.chWidth for j in range(self.nchan)])
                tb.putcell('EFFECTIVE_BW', i, [freq.chWidth for j in range(self.nchan)])
                tb.putcell('RESOLUTION', i, [freq.chWidth for j in range(self.nchan)])
                tb.putcell('FLAG_ROW', i, False)
                tb.putcell('FREQ_GROUP', i, i + 1)
                tb.putcell('FREQ_GROUP_NAME', i, 'group%i' % (i + 1))
                tb.putcell('IF_CONV_CHAIN', i, i)
                tb.putcell('NAME', i, "IF %i, %i channels" % (i + 1, self.nchan))
                tb.putcell('NET_SIDEBAND', i, 0)
                tb.putcell('NUM_CHAN', i, self.nchan)
                tb.putcell('TOTAL_BANDWIDTH', i, freq.totalBW)

            tb.flush()
            tb.close()

        def _write_main_table(self):
            """
            Write the main table.
            """

            # Main

            nBand = len(self.freq)

            # TODO - Where to fetch OBS info from ARL

            # obs = ephem.Observer()
            # obs.lat = arrayGeo.lat * numpy.pi / 180
            # obs.lon = arrayGeo.lng * numpy.pi / 180
            # obs.elev = arrayGeo.elv * numpy.pi / 180
            # obs.pressure = 0

            mapper = self.array[0]['mapper']

            col1 = tableutil.makearrcoldesc('UVW', 0.0, 1,
                                            comment='Vector with uvw coordinates (in meters)',
                                            keywords={'QuantumUnits': ['m', 'm', 'm'],
                                                    'MEASINFO': {'type': 'uvw', 'Ref': 'ITRF'}
                                                    })
            col2 = tableutil.makearrcoldesc('FLAG', False, 2,
                                            comment='The data flags, array of bools with same shape as data')
            col3 = tableutil.makearrcoldesc('FLAG_CATEGORY', False, 3,
                                            comment='The flag category, NUM_CAT flags for each datum',
                                            keywords={'CATEGORY': ['', ]})
            col4 = tableutil.makearrcoldesc('WEIGHT', 1.0, 1,
                                            valuetype='float',
                                            comment='Weight for each polarization spectrum')
            col5 = tableutil.makearrcoldesc('SIGMA', 9999., 1,
                                            valuetype='float',
                                            comment='Estimated rms noise for channel with unity bandpass response')
            col6 = tableutil.makescacoldesc('ANTENNA1', 0,
                                            comment='ID of first antenna in interferometer')
            col7 = tableutil.makescacoldesc('ANTENNA2', 0,
                                            comment='ID of second antenna in interferometer')
            col8 = tableutil.makescacoldesc('ARRAY_ID', 0,
                                            comment='ID of array or subarray')
            col9 = tableutil.makescacoldesc('DATA_DESC_ID', 0,
                                            comment='The data description table index')
            col10 = tableutil.makescacoldesc('EXPOSURE', 0.0,
                                            comment='he effective integration time',
                                            keywords={'QuantumUnits': ['s', ]})
            col11 = tableutil.makescacoldesc('FEED1', 0,
                                            comment='The feed index for ANTENNA1')
            col12 = tableutil.makescacoldesc('FEED2', 0,
                                            comment='The feed index for ANTENNA2')
            col13 = tableutil.makescacoldesc('FIELD_ID', 0,
                                            comment='Unique id for this pointing')
            col14 = tableutil.makescacoldesc('FLAG_ROW', False,
                                            comment='Row flag - flag all data in this row if True')
            col15 = tableutil.makescacoldesc('INTERVAL', 0.0,
                                            comment='The sampling interval',
                                            keywords={'QuantumUnits': ['s', ]})
            col16 = tableutil.makescacoldesc('OBSERVATION_ID', 0,
                                            comment='ID for this observation, index in OBSERVATION table')
            col17 = tableutil.makescacoldesc('PROCESSOR_ID', -1,
                                            comment='Id for backend processor, index in PROCESSOR table')
            col18 = tableutil.makescacoldesc('SCAN_NUMBER', 1,
                                            comment='Sequential scan number from on-line system')
            col19 = tableutil.makescacoldesc('STATE_ID', -1,
                                            comment='ID for this observing state')
            col20 = tableutil.makescacoldesc('TIME', 0.0,
                                            comment='Modified Julian Day',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })
            col21 = tableutil.makescacoldesc('TIME_CENTROID', 0.0,
                                            comment='Modified Julian Day',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })
            col22 = tableutil.makearrcoldesc("DATA", 0j, 2,
                                            valuetype='complex',
                                            comment='The data column')

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8, col9,
                                        col10, col11, col12, col13, col14, col15, col16,
                                        col17, col18, col19, col20, col21, col22])
            tb = table("%s" % self.basename, desc, nrow=0, ack=False)

            i = 0
            s = 1
            _sourceTable = []
            for dataSet in self.data:
                # Sort the data by packed baseline
                # try:
                #     order = dataSet
                # except NameError:
                order = dataSet.argsort(mapper=mapper, shift=16)

                # Deal with defininig the values of the new data set
                if dataSet.pol == self.stokes[0]:
                    ## Figure out the new date/time for the observation
                    # TODO @Wangfeng - observational date & time
                    utc = dataSet.obstime #. astro.taimjd_to_utcjd(dataSet.obstime)
                    # date = astro.get_date(utc)
                    # date.hours = 0
                    # date.minutes = 0
                    # date.seconds = 0
                    utc0 = 2458485.0 # 2019.1.1

                    ### Real-live sources (ephem.Body instances)
                    name = 'TEST' #dataSet.source.name

                    ## Update the source ID
                    try:
                        sourceID = _sourceTable.index(name)
                    except ValueError:
                        _sourceTable.append(name)
                        sourceID = _sourceTable.index(name)

                    ## Compute the uvw coordinates of all baselines
                    # if dataSet.source == 'z':
                    #     HA = 0.0
                    #     dec = equ.dec
                    # else:
                    #     HA = (obs.sidereal_time() - dataSet.source.ra) * 12 / numpy.pi
                    #     dec = dataSet.source.dec * 180 / numpy.pi

                    # Just for testing
                    obs = None
                    HA = 0.0
                    dec = 0.0
                    uvwCoords = dataSet.get_uvw(HA, dec, obs)

                    ## Populate the metadata
                    ### Add in the baselines
                    try:
                        ant1List
                        ant2List
                    except NameError:
                        a1List, a2List = [], []
                        for o in order:
                            antenna1, antenna2 = dataSet.baselines[o]
                            a1List.append(antenna1)
                            a2List.append(antenna2)
                        ant1List = a1List
                        ant2List = a2List

                    ### Add in the new u, v, and w coordinates
                    uvwList = uvwCoords[order, :]

                    ### Add in the new date/time and integration time
                    # timeList = [utc - astro.MJD_OFFSET for bl in dataSet.baselines]
                    # inttimeList = [dataSet.inttime for bl in dataSet.baselines]
                    # timeList = [(utc - astro.MJD_OFFSET) * 86400 + dataSet.inttime / 2.0 for bl in dataSet.baselines]
                    inttimeList = [2 for bl in dataSet.baselines]
                    # timeList = [utc * 86400 + 0./ 2.0 for bl in dataSet.baselines]  #dataSet.inttime 
                    timeList = [1* 86400 + 0./ 2.0 for bl in dataSet.baselines]  #dataSet.inttime 

                    ### Add in the new new source ID and name
                    sourceList = [sourceID for bl in dataSet.baselines]

                    ### Zero out the visibility data
                    try:
                        matrix.shape = (len(order), self.nStokes, nBand * self.nchan)
                        matrix *= 0.0
                    except NameError:
                        matrix = numpy.zeros((len(order), self.nStokes, self.nchan * nBand), dtype=numpy.complex64)

                # Save the visibility data in the right order
                matrix[:, self.stokes.index(dataSet.pol), :] = dataSet.visibilities[order, :]

                # Deal with saving the data once all of the polarizations have been added to 'matrix'
                if dataSet.pol == self.stokes[-1]:
                    nBL = uvwList.shape[0]
                    tb.addrows(nBand * nBL)

                    matrix.shape = (len(order), self.nStokes, nBand, self.nchan)

                    for j in range(nBand):
                        fg = numpy.zeros((nBL, self.nStokes, self.nchan), dtype=numpy.bool)
                        fc = numpy.zeros((nBL, self.nStokes, self.nchan, 1), dtype=numpy.bool)
                        wg = numpy.ones((nBL, self.nStokes))
                        sg = numpy.ones((nBL, self.nStokes)) * 9999

                        tb.putcol('UVW', uvwList, i, nBL)
                        tb.putcol('FLAG', fg.transpose(0, 2, 1), i, nBL)
                        tb.putcol('FLAG_CATEGORY', fc.transpose(0, 3, 2, 1), i, nBL)
                        tb.putcol('WEIGHT', wg, i, nBL)
                        tb.putcol('SIGMA', sg, i, nBL)
                        tb.putcol('ANTENNA1', ant1List, i, nBL)
                        tb.putcol('ANTENNA2', ant2List, i, nBL)
                        tb.putcol('ARRAY_ID', [0, ] * nBL, i, nBL)
                        tb.putcol('DATA_DESC_ID', [j, ] * nBL, i, nBL)
                        tb.putcol('EXPOSURE', inttimeList, i, nBL)
                        tb.putcol('FEED1', [0, ] * nBL, i, nBL)
                        tb.putcol('FEED2', [0, ] * nBL, i, nBL)
                        tb.putcol('FIELD_ID', sourceList, i, nBL)
                        tb.putcol('FLAG_ROW', [False, ] * nBL, i, nBL)
                        tb.putcol('INTERVAL', inttimeList, i, nBL)
                        tb.putcol('OBSERVATION_ID', [0, ] * nBL, i, nBL)
                        tb.putcol('PROCESSOR_ID', [-1, ] * nBL, i, nBL)
                        tb.putcol('SCAN_NUMBER', [s, ] * nBL, i, nBL)
                        tb.putcol('STATE_ID', [-1, ] * nBL, i, nBL)
                        tb.putcol('TIME', timeList, i, nBL)
                        tb.putcol('TIME_CENTROID', timeList, i, nBL)
                        tb.putcol('DATA', matrix[..., j, :].transpose(0, 2, 1), i, nBL)
                        i += nBL
                    s += 1

            tb.flush()
            tb.close()

            # Data description

            col1 = tableutil.makescacoldesc('FLAG_ROW', False,
                                            comment='Flag this row')
            col2 = tableutil.makescacoldesc('POLARIZATION_ID', 0,
                                            comment='Pointer to polarization table')
            col3 = tableutil.makescacoldesc('SPECTRAL_WINDOW_ID', 0,
                                            comment='Pointer to spectralwindow table')

            desc = tableutil.maketabdesc([col1, col2, col3])
            tb = table("%s/DATA_DESCRIPTION" % self.basename, desc, nrow=nBand, ack=False)

            for i in range(nBand):
                tb.putcell('FLAG_ROW', i, False)
                tb.putcell('POLARIZATION_ID', i, 0)
                tb.putcell('SPECTRAL_WINDOW_ID', i, i)

            tb.flush()
            tb.close()

        def _write_misc_required_tables(self):
            """
            Write the other tables that are part of the measurement set but
            don't contain anything by default.
            """

            # Flag command

            col1 = tableutil.makescacoldesc('TIME', 0.0,
                                            comment='Midpoint of interval for which this flag is valid',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })
            col2 = tableutil.makescacoldesc('INTERVAL', 0.0,
                                            comment='Time interval for which this flag is valid',
                                            keywords={'QuantumUnits': ['s', ]})
            col3 = tableutil.makescacoldesc('TYPE', 'flag',
                                            comment='Type of flag (FLAG or UNFLAG)')
            col4 = tableutil.makescacoldesc('REASON', 'reason',
                                            comment='Flag reason')
            col5 = tableutil.makescacoldesc('LEVEL', 0,
                                            comment='Flag level - revision level')
            col6 = tableutil.makescacoldesc('SEVERITY', 0,
                                            comment='Severity code (0-10)')
            col7 = tableutil.makescacoldesc('APPLIED', False,
                                            comment='True if flag has been applied to main table')
            col8 = tableutil.makescacoldesc('COMMAND', 'command',
                                            comment='Flagging command')

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8])
            tb = table("%s/FLAG_CMD" % self.basename, desc, nrow=0, ack=False)

            tb.flush()
            tb.close()

            # History

            col1 = tableutil.makescacoldesc('TIME', 0.0,
                                            comment='Timestamp of message',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })
            col2 = tableutil.makescacoldesc('OBSERVATION_ID', 0,
                                            comment='Observation id (index in OBSERVATION table)')
            col3 = tableutil.makescacoldesc('MESSAGE', 'message',
                                            comment='Log message')
            col4 = tableutil.makescacoldesc('PRIORITY', 'NORMAL',
                                            comment='Message priority')
            col5 = tableutil.makescacoldesc('ORIGIN', 'origin',
                                            comment='(Source code) origin from which message originated')
            col6 = tableutil.makescacoldesc('OBJECT_ID', 0,
                                            comment='Originating ObjectID')
            col7 = tableutil.makescacoldesc('APPLICATION', 'application',
                                            comment='Application name')
            col8 = tableutil.makearrcoldesc('CLI_COMMAND', 'command', 1,
                                            comment='CLI command sequence')
            col9 = tableutil.makearrcoldesc('APP_PARAMS', 'params', 1,
                                            comment='Application parameters')

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8, col9])
            tb = table("%s/HISTORY" % self.basename, desc, nrow=0, ack=False)

            tb.flush()
            tb.close()

            # POINTING

            col1 = tableutil.makescacoldesc('ANTENNA_ID', 0,
                                            comment='Antenna Id')
            col2 = tableutil.makescacoldesc('TIME', 0.0,
                                            comment='Time interval midpoint',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })
            col3 = tableutil.makescacoldesc('INTERVAL', 0.0,
                                            comment='Time interval',
                                            keywords={'QuantumUnits': ['s', ]})
            col4 = tableutil.makescacoldesc('NAME', 'name',
                                            comment='Pointing position name')
            col5 = tableutil.makescacoldesc('NUM_POLY', 0,
                                            comment='Series order')
            col6 = tableutil.makescacoldesc('TIME_ORIGIN', 0.0,
                                            comment='Time origin for direction',
                                            keywords={'QuantumUnits': ['s', ],
                                                    'MEASINFO': {'type': 'epoch', 'Ref': 'UTC'}
                                                    })
            col7 = tableutil.makearrcoldesc('DIRECTION', 0.0, 2,
                                            comment='Antenna pointing direction as polynomial in time',
                                            keywords={'QuantumUnits': ['rad', 'rad'],
                                                    'MEASINFO': {'type': 'direction', 'Ref': 'J2000'}
                                                    })
            col8 = tableutil.makearrcoldesc('TARGET', 0.0, 2,
                                            comment='target direction as polynomial in time',
                                            keywords={'QuantumUnits': ['rad', 'rad'],
                                                    'MEASINFO': {'type': 'direction', 'Ref': 'J2000'}
                                                    })
            col9 = tableutil.makescacoldesc('TRACKING', True,
                                            comment='Tracking flag - True if on position')

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7, col8, col9])
            tb = table("%s/POINTING" % self.basename, desc, nrow=0, ack=False)

            tb.flush()
            tb.close()

            # Processor

            col1 = tableutil.makescacoldesc('TYPE', 'type',
                                            comment='Processor type')
            col2 = tableutil.makescacoldesc('SUB_TYPE', 'subtype',
                                            comment='Processor sub type')
            col3 = tableutil.makescacoldesc('TYPE_ID', 0,
                                            comment='Processor type id')
            col4 = tableutil.makescacoldesc('MODE_ID', 0,
                                            comment='Processor mode id')
            col5 = tableutil.makescacoldesc('FLAG_ROW', False,
                                            comment='flag')

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5])
            tb = table("%s/PROCESSOR" % self.basename, desc, nrow=0, ack=False)

            tb.flush()
            tb.close()

            # State

            col1 = tableutil.makescacoldesc('SIG', True,
                                            comment='True for a source observation')
            col2 = tableutil.makescacoldesc('REF', False,
                                            comment='True for a reference observation')
            col3 = tableutil.makescacoldesc('CAL', 0.0,
                                            comment='Noise calibration temperature',
                                            keywords={'QuantumUnits': ['K', ]})
            col4 = tableutil.makescacoldesc('LOAD', 0.0,
                                            comment='Load temperature',
                                            keywords={'QuantumUnits': ['K', ]})
            col5 = tableutil.makescacoldesc('SUB_SCAN', 0,
                                            comment='Sub scan number, relative to scan number')
            col6 = tableutil.makescacoldesc('OBS_MODE', 'mode',
                                            comment='Observing mode, e.g., OFF_SPECTRUM')
            col7 = tableutil.makescacoldesc('FLAG_ROW', False,
                                            comment='Row flag')

            desc = tableutil.maketabdesc([col1, col2, col3, col4, col5, col6, col7])
            tb = table("%s/STATE" % self.basename, desc, nrow=0, ack=False)

            tb.flush()
            tb.close()



    class Ms(WriteMs):
        """
        Class for storing visibility data and writing the data, along with array
        geometry, frequency setup, etc., to a CASA measurement set.
        """
        
        _STOKES_CODES = STOKES_CODES
        
        def __init__(self, filename, ref_time=0.0, verbose=False, ifdelete=False):
            """
            Initialize a new MeasurementSets object using a filename and a reference time 
            given in seconds since the UNIX 1970 ephem, a python datetime object, or a 
            string in the format of 'YYYY-MM-DDTHH:MM:SS'.
            
            """
            super(Ms, self).__init__(filename, ref_time, verbose, ifdelete=ifdelete)

except ImportError:
    import warnings
    warnings.warn('Cannot import casacore.tables, MS support disabled', ImportWarning)

    raise RuntimeError("Cannot import casacore.tables, MS support disabled")
