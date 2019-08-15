import copy
import datetime
import os
import sys
from collections import defaultdict
from itertools import tee

import tqdm
import seaborn as sns

import time
from csep import load_stochastic_event_sets, load_comcat
from csep.utils.time import utc_now_epoch, datetime_to_utc_epoch, epoch_time_to_utc_datetime
from csep.utils.spatial import masked_region, california_relm_region
from csep.utils.basic_types import Polygon
from csep.utils.scaling_relationships import WellsAndCoppersmith
from csep.utils.comcat import get_event_by_id
from csep.utils.constants import SECONDS_PER_ASTRONOMICAL_YEAR
from csep.core.evaluations import NumberTest, MagnitudeTest, LikelihoodAndSpatialTest, CumulativeEventPlot, \
    MagnitudeHistogram, ConditionalRatePlot, BValueTest, TotalEventRateDistribution, \
    InterEventDistanceDistribution, InterEventTimeDistribution, SpatialLikelihoodPlot
from file import get_relative_path


sns.set()


def generate_table_from_results(results, mws, tests=('n-test', 'm-test', 's-test', 'ietd-test', 'bv-test', 'iedd-test')):
    table = []
    header = mws
    header.insert(0, ' ')
    table.append(tuple(header))
    for test in tests:
        row = []
        row.append('<b>' + test + '</b>')
        test_results = results[test]
        for mw in test_results.keys():
            try:
                row.append(test_results[mw].quantile)
            except AttributeError:
                pass
        table.append(tuple(row))
    return table

# MAIN SCRIPT BELOW HERE

# set up basic stuff, most of this stuff coming from ucerf3
# event_id = 'ci38443183' # mw 6.4 ridgecrest, should be in later editions of ucerf3 json format
# filename = '/Users/wsavran/Desktop/working/ucerf3_ridgecrest_eq/searles_valley_m64_point_src/results_complete.bin'
# plot_dir = '/Users/wsavran/Desktop/working/ucerf3_ridgecrest_eq/searles_valley_m64_point_src/plotting'
from documents import ResultsNotebook

event_id = 'ci38457511' # mw 7.1
filename = '/Users/wsavran/Desktop/working/ucerf3_ridgecrest_eq/searles_valley_m71_finite_flt/results_complete.bin'
plot_dir = '/Users/wsavran/Desktop/working/ucerf3_ridgecrest_eq/searles_valley_m71_finite_flt/plotting'
n_cat = 1000
event = get_event_by_id(event_id)
origin_epoch = datetime_to_utc_epoch(event.time)
rupture_length = WellsAndCoppersmith.mag_length_strike_slip(event.magnitude) * 1000
aftershock_polygon = Polygon.from_great_circle_radius((event.longitude, event.latitude),
                                                      3*rupture_length, num_points=100)
aftershock_region = masked_region(california_relm_region(), aftershock_polygon)
end_epoch = utc_now_epoch()
time_horizon = (end_epoch - origin_epoch) / SECONDS_PER_ASTRONOMICAL_YEAR / 1000
event_time = event.time.replace(tzinfo=datetime.timezone.utc)

# Download comcat catalog
print('Loading Comcat.')
comcat = load_comcat(event_time, epoch_time_to_utc_datetime(end_epoch),
                          min_magnitude=2.50,
                          min_latitude=31.50, max_latitude=43.00,
                          min_longitude=-125.40, max_longitude=-113.10)
comcat = comcat.filter_spatial(aftershock_region)
print(comcat)

# these classes must implement process_catalog() and evaluate()
# calling evaluate should return an EvaluationResult namedtuple
data_products = {
     # needs event count per catalog
     'n-test': NumberTest(),
     'm-test': MagnitudeTest(),
     'l-test': LikelihoodAndSpatialTest(),
     'cum-plot': CumulativeEventPlot(origin_epoch, end_epoch),
     'mag-hist': MagnitudeHistogram(calc=False),
     'crd-plot': ConditionalRatePlot(calc=False),
     'bv-test': BValueTest(),
     'like-plot': SpatialLikelihoodPlot(calc=False),
}

t0 = time.time()
u3 = load_stochastic_event_sets(filename=filename, type='ucerf3', name='UCERF3-ETAS', region=aftershock_region)
for i, cat in tqdm.tqdm(enumerate(u3), total=n_cat, position=0):
    cat_filt = cat.filter(f'origin_time < {end_epoch}').filter_spatial(aftershock_region)
    for name, calc in data_products.items():
        calc.process_catalog(copy.copy(cat_filt))
    if (i+1) % n_cat == 0:
        break
t1 = time.time()
print(f'Processed catalogs in {t1-t0} seconds')

# share data where applicable
data_products['mag-hist'].data = data_products['m-test'].data
data_products['crd-plot'].data = data_products['l-test'].data
data_products['like-plot'].data = data_products['l-test'].data

# finalizes
results = {}
for name, calc in data_products.items():
    print(f'Finalizing calculations for {name} and plotting')
    result = calc.evaluate(comcat, args=(u3, time_horizon, end_epoch, n_cat))
    # store results for later, maybe?
    results[name] = result
    # plot, and store in plot_dir
    calc.plot(result, plot_dir, show=False)
t2 = time.time()
print(f"Evaluated forecasts in {t2-t1} seconds")
print(f"Finished everything in {t2-t0} seconds with average time per catalog of {(t2-t0)/n_cat} seconds")

# build report with custom layout
# create the notebook for results
notebook = ResultsNotebook('results_benchmark.ipynb')
# introduction is fixed,  might change to make more general
notebook.add_introduction(adict={'simulation_name': 'Ridgecrest Mw 7.1',
                                'origin_time': epoch_time_to_utc_datetime(origin_epoch),
                                'evaluation_time': epoch_time_to_utc_datetime(end_epoch),
                                'catalog_source': 'Comcat',
                                'forecast_name': 'UCERF3-ETAS',
                                'num_simulations': n_cat})
notebook.add_sub_heading('Visual Overview of Forecast', 1, "")
# add cumulative event counts plot, notice the tuple is wrapped in a list, indicates 1 row
notebook.add_result_figure('Cumulative Event Counts', 2, list(map(get_relative_path, data_products['cum-plot'].fnames)))
# Magnitude histogram (only plot the one for minimum magnitude, results are ordered by map)
notebook.add_result_figure('Magnitude Histogram', 2, list(map(get_relative_path, data_products['mag-hist'].fnames)))
notebook.add_result_figure('Conditional Rate Density with Observations', 2, list(map(get_relative_path, data_products['crd-plot'].fnames)))
notebook.add_result_figure('Normalized Likelihood Per Event', 2, list(map(get_relative_path, data_products['like-plot'].fnames)))
notebook.add_sub_heading('CSEP Consistency Tests', 1, "<b>Note</b>: These tests are still in development. Feedback appreciated.")
notebook.add_result_figure('Number Test', 2, list(map(get_relative_path, data_products['n-test'].fnames)))
notebook.add_result_figure('Magnitude Test', 2, list(map(get_relative_path, data_products['m-test'].fnames)))
notebook.add_result_figure('Spatial Test', 2, list(map(get_relative_path, data_products['l-test'].fnames['s-test'])))
notebook.add_result_figure('Likelihood Test', 2, list(map(get_relative_path, data_products['l-test'].fnames['l-test'])))
notebook.add_sub_heading('One-point Statistics', 1, "")
notebook.add_result_figure('B-Value Test', 2, list(map(get_relative_path, data_products['bv-test'].fnames)))
# notebook.add_sub_heading('Distribution Statistics', 1, "")
# notebook.add_result_figure('Inter-event Distance Distribution', 2, [results['iedd-test_plot']])
# notebook.add_result_figure('Inter-event Time Distribution', 2, [results['ietd-test_plot']])
# notebook.add_result_figure('Total Event Rate Distribution', 2, [results['terd-test_plot']])
# table should be a list of tuples, where each tuple is the row
# table = generate_table_from_results(results, data_products['n-test'].mws, tests=data_products.keys())
# assemble the results from the dictionary
# notebook.add_sub_heading('Results Summary', 1, notebook.get_table(table))
# calling this produces the toc, and writes output.
notebook.finalize(os.path.dirname(filename))

t1 = time.time()
print(f'Completed all processing in {t1-t0} seconds.')