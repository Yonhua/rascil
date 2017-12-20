""" Pipelines expressed as dask bags
"""

import logging

from astropy import units as u
from astropy.coordinates import SkyCoord
from dask import bag

from arl.calibration.operations import apply_gaintable, create_gaintable_from_blockvisibility
from arl.data.polarisation import PolarisationFrame
from arl.graphs.bags import predict_bag, map_record
from arl.util.testing_support import create_named_configuration, simulate_gaintable, \
    create_low_test_image_from_gleam, create_low_test_beam
from arl.visibility.base import create_blockvisibility, create_visibility

log = logging.getLogger(__name__)


def simulate_vis_bag(config='LOWBD2-CORE',
                     phasecentre=SkyCoord(ra=+15.0 * u.deg, dec=-60.0 * u.deg, frame='icrs', equinox='J2000'),
                     frequency=None, channel_bandwidth=None, times=None,
                     polarisation_frame=PolarisationFrame("stokesI"), order='frequency',
                     format='blockvis',
                     **kwargs) -> bag:
    """ Create a bag to simulate an observation

    The simulation step can generate a single BlockVisibility or a list of BlockVisibility's.
    The parameter keyword determines the way that the list is constructed.
    If order='frequency' then len(frequency) BlockVisibility's with all times are created.
    If order='time' then  len(times) BlockVisibility's with all frequencies are created.
    If order = 'both' then len(times) * len(times) BlockVisibility's are created each with
    a single time and frequency. If order = None then all data are created in one BlockVisibility.

    The output format can be either 'blockvis' (for calibration) or 'vis' (for imaging)

    :param config: Name of configuration: def LOWBDS-CORE
    :param phasecentre: Phase centre def: SkyCoord(ra=+15.0 * u.deg, dec=-60.0 * u.deg, frame='icrs', equinox='J2000')
    :param frequency: def [1e8]
    :param channel_bandwidth: def [1e6]
    :param times: Observing times in radians: def [0.0]
    :param polarisation_frame: def PolarisationFrame("stokesI")
    :param order: 'time' or 'frequency' or 'both' or None: def 'frequency'
    :param format: 'blockvis' or 'vis': def 'blockvis'
    :param kwargs:
    :return: vis_bag with different frequencies in different elements
    """
    if format == 'vis':
        create_vis = create_visibility
    else:
        create_vis = create_blockvisibility
    
    if times is None:
        times = [0.0]
    if channel_bandwidth is None:
        channel_bandwidth = [1e6]
    if frequency is None:
        frequency = [1e8]
    conf = create_named_configuration(config, **kwargs)
    
    if order == 'time':
        log.debug("simulate_vis_bag: Simulating distribution in %s" % order)
        vis_bag = bag.from_sequence([{'timewin': i,
                                      'vis': create_vis(conf, [times[i]], frequency=frequency,
                                                        channel_bandwidth=channel_bandwidth,
                                                        weight=1.0, phasecentre=phasecentre,
                                                        polarisation_frame=polarisation_frame, **kwargs)}
                                     for i, time in enumerate(times)])
    
    elif order == 'frequency':
        log.debug("simulate_vis_bag: Simulating distribution in %s" % order)
        vis_bag = bag.from_sequence([{'freqwin': j,
                                      'vis': create_vis(conf, times, frequency=[frequency[j]],
                                                        channel_bandwidth=[channel_bandwidth[j]],
                                                        weight=1.0, phasecentre=phasecentre,
                                                        polarisation_frame=polarisation_frame, **kwargs)}
                                     for j, _ in enumerate(frequency)])
    
    elif order == 'both':
        log.debug("simulate_vis_bag: Simulating distribution in time and frequency")
        vis_bag = bag.from_sequence([{'timewin': i, 'freqwin': j,
                                      'vis': create_vis(conf, [times[i]], frequency=[frequency[j]],
                                                        channel_bandwidth=[channel_bandwidth[j]],
                                                        weight=1.0, phasecentre=phasecentre,
                                                        polarisation_frame=polarisation_frame, **kwargs)}
                                     for j, _ in enumerate(frequency) for i, _ in enumerate(times)])
    
    elif order is None:
        log.debug("simulate_vis_bag: Simulating into single %s" % format)
        vis_bag = bag.from_sequence([{'vis': create_vis(conf, times, frequency=frequency,
                                                        channel_bandwidth=channel_bandwidth,
                                                        weight=1.0, phasecentre=phasecentre,
                                                        polarisation_frame=polarisation_frame, **kwargs)}])
    else:
        raise NotImplementedError("order $s not known" % order)
    return vis_bag

def corrupt_vis_bag(vis_bag, gt_bag=None, **kwargs):
    """ Create a graph to apply gain errors to a vis_bag

    :param vis_bag:
    :param gt_bag: Optional gain table graph
    :param kwargs:
    :return:
    """
    
    def corrupt_vis(vis, gt, **kwargs):
        if gt is None:
            gt = create_gaintable_from_blockvisibility(vis, **kwargs)
            gt = simulate_gaintable(gt, **kwargs)
        return apply_gaintable(vis, gt)
    
    return vis_bag.map(map_record, corrupt_vis, key='vis', gt=gt_bag, **kwargs)