#!/usr/bin/env python
import os
import sys
import re
from datetime import datetime,timedelta
import gdal
import numpy as np
from csaps import UnivariateCubicSmoothingSpline
from matplotlib.dates import date2num
from optparse import OptionParser,IndentedHelpFormatter

# Read options
parser = OptionParser(formatter=IndentedHelpFormatter(max_help_position=200,width=200))
parser.set_usage('Usage: %prog collocated_geotiff_file [options]')
parser.add_option('-s','--start',default=None,help='Start date of the analysis in the format YYYYMMDD (%default)')
parser.add_option('-e','--end',default=None,help='End date of the analysis in the format YYYYMMDD (%default)')
parser.add_option('-m','--mask',default=None,help='Mask file in GeoTIFF/npy format (%default)')
(opts,args) = parser.parse_args()
if len(args) < 1:
    parser.print_help()
    sys.exit(0)
input_fnam = args[0]

xstp = 10.0
ystp = -10.0
xmin,xmax,ymin,ymax = (743800.0,756800.0,9236000.0,9251800.0)
xg,yg = np.meshgrid(np.arange(xmin,xmax+0.1*xstp,xstp),np.arange(ymax,ymin-0.1*ystp,ystp))
ngrd = xg.size
ny,nx = xg.shape

if opts.mask is not None:
    if os.path.splitext(opts.mask)[1].lower() == '.npy':
        mask = np.load(opts.mask)
    else:
        ds = gdal.Open(opts.mask)
        mask = ds.ReadAsArray()
        ds = None
    if mask.shape != xg.shape:
        raise ValueError('Error, mask.shape={}, xg.shape={}'.format(mask.shape,xg.shape))

ibands = [4,8,17]
nband = len(ibands)
# Create output file
ndvi_data = np.full((4,ny,nx),np.nan,dtype=np.float32)

ds = gdal.Open(input_fnam)
data = ds.ReadAsArray()
band_list = []
band_indx = [[] for i in ibands]
dtim_list = [[] for i in ibands]
for i in range(len(data)):
    band = ds.GetRasterBand(i+1).GetDescription()
    band_list.append(band)
    #sys.stderr.write(band+'\n')
    m = re.search('band_(\d+)_(\d+)$',band)
    if not m:
        raise ValueError('Error in finding date >>> '+band)
    band_num = int(m.group(1))
    dtim = datetime.strptime(m.group(2),'%Y%m%d')
    try:
        j = ibands.index(band_num)
        band_indx[j].append(i)
        dtim_list[j].append(dtim)
    except Exception:
        pass
ds = None
band_list = np.array(band_list)
band_indx = np.array(band_indx)
dtim_list = np.array(dtim_list)
for i in range(1,nband):
    if not np.all(dtim_list[i] == dtim_list[0]):
        raise ValueError('Error, different time {}'.format(i))
dtim = dtim_list[0].copy()
ntim = date2num(dtim)
if opts.start is not None:
    dmin = datetime.strptime(opts.start,'%Y%m%d')
else:
    dmin = dtim.min()
if opts.end is not None:
    dmax = datetime.strptime(opts.end,'%Y%m%d')
else:
    dmax = dtim.max()
nmin = date2num(dmin)
nmax = date2num(dmax)

all_bands = []
for i in range(nband):
    all_bands.append(data[band_indx[i]])
all_bands = np.array(all_bands)
all_bands[:nband-1] *= 1.0e-4

# Apply Flag and calculate NDVI -----------------------------------------------#
scl_data = all_bands[ibands.index(17)]
cnd = (scl_data < 3.9) | (scl_data > 7.1)
for i in range(0,nband-1):
    all_bands[i][cnd] = np.nan
b04_data = all_bands[ibands.index(4)]
b08_data = all_bands[ibands.index(8)]

ndvi = (b08_data-b04_data)/(b08_data+b04_data)

xx = np.arange(np.floor(ntim.min()),np.ceil(ntim.max())+0.1,1.0)
cndx = (xx > nmin) & (xx < nmax)
for iline in range(ny):
#for iline in range(825, 826):
    for ipixel in range(nx):
    #for ipixel in range(829, 830):
        if opts.mask is not None and mask[iline,ipixel]==0:
            continue
        yi = ndvi[:,iline,ipixel]
        cnd = ~np.isnan(yi)
        if cnd.sum() < 5:
            continue
        xc = ntim[cnd]
        yc = yi[cnd]
        sp = UnivariateCubicSmoothingSpline(xc,yc,smooth=2.0e-3)
        yy = sp(xx)
        # Find planting/heading stage based on peak points
        indx = np.argmin(yy[cndx])
        ndvi_data[0,iline,ipixel] = xx[cndx][indx]  # Put date of minNDVI (this is defined as planting stage)
        ndvi_data[1,iline,ipixel] = yy[cndx][indx]  # Put minNDVI value
        indx = np.argmax(yy[cndx])
        ndvi_data[2,iline,ipixel] = xx[cndx][indx]  # Put date of maxNDVI (this is defined as heading stage)
        ndvi_data[3,iline,ipixel] = yy[cndx][indx]  # Put maxNDVI value
np.save('ndvi_data.npy',ndvi_data)

# Output results
drv = gdal.GetDriverByName('GTiff')
ds = drv.Create(outnam,nx,ny,4,gdal.GDT_Float32,['COMPRESS=LZW','TILED=YES'])
ds.SetGeoTransform((xmin,xstp,0.0,ymax,0.0,ystp))
srs = osr.SpatialReference()
srs.ImportFromEPSG(32748)
ds.SetProjection(srs.ExportToWkt())
band_name = ['planting_date','planting_ndvi','heading_date','heading_ndvi']
for i in range(4):
    band = ds.GetRasterBand(i+1)
    band.WriteArray(ndvi_data[i])
    band.SetDescription(band_name[i])
band.SetNoDataValue(np.nan) # The TIFFTAG_GDAL_NODATA only support one value per dataset
ds.FlushCache()
ds = None # close dataset
