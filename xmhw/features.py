#!/usr/bin/env python
# coding: utf-8
# Copyright 2020 ARC Centre of Excellence for Climate Extremes
# author: Paola Petrelli <paola.petrelli@utas.edu.au>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import xarray as xr
import numpy as np
import sys
from .exception import XmhwException


def mhw_ds(ds, ts, thresh, seas, tdim='time'):
    """ Calculate and add to dataset mhw properties
    """
    # assign event coordinate to dataset
    ds = ds.assign_coords({'event': ds.events})
    #  Would calling this new dimension 'time' regardless of tdim create issues?
    ds['event'].assign_coords({tdim: ds[tdim]})

    # get temp, climatologies values for events
    ismhw = ~np.isnan(ds.events)
    mhw_temp = ts.where(ismhw)
    mhw_seas = xr.where(ismhw, seas.sel(doy=ismhw.doy.values).values, np.nan)
    mhw_thresh = xr.where(ismhw, thresh.sel(doy=ismhw.doy.values).values, np.nan)
    # get difference between ts and seasonal average, needed to calculate onset and decline rates later
    anom = (ts - seas.sel(doy=ts.doy))
    ds['anom_plus'] = anom.shift(**{tdim: 1})
    ds['anom_minus'] = anom.shift(**{tdim: 1})
    ds['seas'] = mhw_seas
    ds['thresh'] = mhw_thresh
    relSeas = mhw_temp - mhw_seas
    relSeas['event'] = ds.events
    relThresh = mhw_temp - mhw_thresh
    relThresh['event'] = ds.events
    relThreshNorm = (mhw_temp - mhw_thresh) / (mhw_thresh - mhw_seas)
    relThreshNorm['event'] = ds.events
    # in this version having these as part of the dataset helps to pass them to main mapped function 
    ds['ts'] = ts
    ds['relThresh'] = relThresh
    ds['relSeas'] = relSeas
    ds['relThreshNorm'] = relThreshNorm
    # if I remove this then I need to find a way to pass this series to onset/decline
    ds['mabs'] = mhw_temp

    #From here on work grouping by cell
    ds =ds.groupby('cell').map(call_mhw_features, args=[tdim])
    #ds =ds.groupby('cell').map(groupds_function, args=[mhw_features], farg=tdim, dim='event')
    return ds

def call_mhw_features(dsgroup, tdim):
    return dsgroup.groupby('event').map(mhw_features, args=[tdim])


#def mhw_features(ds, arg='time', axis=0):
def mhw_features(ds, tdim):
    """Calculate all the mhw details for one event 
    """
    # Skip if event is all-nan array
    if len(ds.start.dropna(dim=tdim)) == 0:
        for var in ['end_idx', 'start_idx', 'index_peak', 'intensity_max',
                    'intensity_mean', 'intensity_var', 'intensity_cumulative',
                    'intensity_max_abs', 'intensity_max_relThresh',
                    'intensity_cumulative_relThresh', 'intensity_var_relThresh',
                    'intensity_cumulative_abs', 'intensity_mean_abs',
                    'intensity_var_abs', 'rate_onset', 'rate-decline']:
            ds[var] = np.nan
        #ds['category'] = ""
        ds['category'] = np.nan 
        for var in ['duration_moderate', 'duration_strong',
                    'duration_severe', 'duration_extreme']:
            ds[var] = 0
        ds = ds.drop_vars(['start','end','anom_plus', 'anom_minus', 'seas', 'ts',
           'thresh', 'events', 'relThresh', 'relSeas', 'relThreshNorm', 'mabs'])
        ds =ds.drop_dims(['time'])
        return ds 
    # Save start and end and duration for each event
    ds['end_idx'] =  ds.end[-1]
    ds['start_idx'] =  ds.start[-1]
    # Find anomaly peak for events 
    ds['index_peak'] = ds.relSeas.event[0] + ds.relSeas.argmax()
    ds['intensity_max'] = ds.relSeas.max()
    ds['intensity_mean'] = ds.relSeas.mean() 
    ds['intensity_var'] = np.sqrt(ds.relSeas.var()) 
    ds['intensity_cumulative'] = ds.relSeas.sum()
    # stats for 
    rel_peak = (ds.index_peak - ds.start_idx).astype(int).values
    ds['intensity_max_relThresh'] = ds.relThresh[rel_peak]
    ds['intensity_max_abs'] = ds.mabs[rel_peak]
    ds['intensity_var_relThresh'] = np.sqrt(ds.relThresh.var()) 
    ds['intensity_cumulative_relThresh'] = ds.relThresh.sum()
    # abs stats
    ds['intensity_mean_abs'] = ds.mabs.mean()
    ds['intensity_var_abs'] = np.sqrt(ds.mabs.var()) 
    ds['intensity_cumulative_abs'] = ds.mabs.sum()
    # Add categories to dataset
    ds = categories(ds)
    ds = onset_decline(ds)
    ds = ds.drop_vars(['start','end','anom_plus', 'anom_minus', 'seas', 'ts',
           'thresh', 'events', 'relThresh', 'relSeas', 'relThreshNorm', 'mabs'])
    ds =ds.drop_dims([tdim])
    #ds = ds.assign_coords({'event': ds.start_idx})
    return ds
    #return ds.drop_vars(['start','end','anom_plus', 'anom_minus', 'seas', 'ts',
    #       'thresh', 'events', 'relThresh', 'relSeas', 'relThreshNorm', 'mabs'])


def categories(ds):
    # define categories
    categories = {1: 'Moderate', 2: 'Strong', 3: 'Severe', 4: 'Extreme'}
    # Fix categories
    #index_peakCat = ds.relThreshNorm.argmax()
    cats = np.floor(1. + ds.relThreshNorm)
    #cat_index = index_cat(cats)
    # temporarily removing this to make it easier to remove nans 
    #ds['category'] = categories[index_cat(cats)] 
    ds['category'] = index_cat(cats) 
    #for k,v in categories.items():
    #    ds['category'] = xr.where(cat_index == k, v, ds['category'])

    # calculate duration of each category
    ds['duration_moderate'] = cat_duration(cats,1)
    ds['duration_strong'] = cat_duration(cats, 2)
    ds['duration_severe'] = cat_duration(cats, 3)
    ds['duration_extreme'] = cat_duration(cats, 4)
    return ds 


def group_function(array, func, farg=None, dim='event'):
    """ Run function on array after groupby on event dimension """
    if farg:
        return array.groupby(dim).reduce(func, arg=farg)
    return array.groupby(dim).reduce(func)


def groupds_function(ds, func, farg=None, dim='event'):
    """ Run function on dataset after groupby on event dimension """
    if farg:
        return ds.groupby(dim).reduce(func, arg=farg, keep_attrs=False)
    return ds.groupby(dim=dim).reduce(func, keep_attrs=False)

def index_cat(array):
    """ Get array maximum and return minimum between peak and 4 , minus 1
        to index category
    """
    peak = np.max(array)
    return np.min([peak, 4])


def cat_duration(array, arg=1):
    """ Return sum for input category (cat)
    """
    return np.sum(array == arg) 


def get_rate(relSeas_peak, relSeas_edge, period):
    """ Calculate onset/decline rate of event
    """
    return (relSeas_peak - relSeas_edge) / period


#def get_edge(relSeas, anom, idx, edge, step):
def get_edge(relSeas, anom, idx, edge):
    """ Return the relative start or end of mhw to calculate respectively onset and decline 
        for onset edge = 0 step = 1, relSeas=relSeas[0]
        for decline edge = len(ts)-1 and step = -1, relSeas=relSeas[-1]
    """
    if idx == edge:
        x = relSeas
    else:
        x = anom
    return 0.5*(relSeas + x)


def get_period(start, end, peak, tsend):
    """ Return the onset/decline period for a mhw 
    """
    x = xr.where(peak == 0, 1, peak)
    onset_period = xr.where(start == 0, x, x + 0.5)
    y = xr.where(peak == tsend, 1, end - start - peak)
    decline_period = xr.where(end == tsend, y, y + 0.5)
    return onset_period, decline_period


def onset_decline(ds):
    """ Calculate rate of onset and decline for each MHW
    """
    start = ds.start_idx.astype(int).values

    end = ds.end_idx.astype(int).values
    peak =ds.index_peak.astype(int).values
    tslen = len(ds.anom_plus)
    onset_period, decline_period = get_period(start, end, peak, tslen)
    relSeas_start = get_edge(ds.relSeas[0], ds.anom_plus[0], start, 0)
    relSeas_end = get_edge(ds.relSeas[-1], ds.anom_minus[-1], end, tslen-1)
    relSeas_peak = ds.relSeas[peak-start]
    onset_rate =  get_rate(relSeas_peak, relSeas_start, onset_period)
    decline_rate =  get_rate(relSeas_peak, relSeas_end, decline_period)
    return ds 


def flip_cold(ds):
    """Flip mhw intensities if cold spell
    """
    for varname in ds.keys():
        if 'intensity' in varname and '_var' not in varname:
            ds[varname] = -1*ds[varname]
    return ds
