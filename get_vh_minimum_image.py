#!/usr/bin/env python
import os
import sys
import re
from datetime import datetime,timedelta
import numpy as np
import tifffile
import xml.etree.ElementTree as ET
from scipy.interpolate import splrep,splev
from scipy.interpolate import griddata
from csaps import UnivariateCubicSmoothingSpline
import gdal
import osr
import matplotlib.pyplot as plt
from matplotlib.dates import date2num
from matplotlib.path import Path
from matplotlib.backends.backend_pdf import PdfPages
from optparse import OptionParser,IndentedHelpFormatter

# Default values
END = datetime.now().strftime('%Y%m%d')
PERIOD = 60 # day
SIGWID = 15.0 # dB
MAXDIS = 100.0 # m
VINT = 100
SHPNAM = os.path.join('New_Test_Sites','New_Test_Sites.shp')
DATNAM = 'transplanting_date.dat'
FIGNAM = 'transplanting_date.pdf'

# Read options
parser = OptionParser(formatter=IndentedHelpFormatter(max_help_position=200,width=200))
parser.set_usage('Usage: %prog collocated_geotiff_file [options]')
parser.add_option('-e','--end',default=END,help='End date of the analysis in the format YYYYMMDD (%default)')
parser.add_option('-p','--period',default=PERIOD,type='int',help='Observation period in day (%default)')
parser.add_option('-i','--ind',default=None,type='int',action='append',help='Selected indices (%default)')
parser.add_option('-w','--sigwid',default=SIGWID,type='float',help='Signal width in day (%default)')
parser.add_option('-m','--maxdis',default=MAXDIS,type='float',help='Max distance in m (%default)')
parser.add_option('-o','--datnam',default=DATNAM,help='Output data name (%default)')
parser.add_option('-F','--fignam',default=FIGNAM,help='Output figure name for debug (%default)')
parser.add_option('--vint',default=VINT,type='int',help='Verbose output interval (%default)')
parser.add_option('-v','--verbose',default=False,action='store_true',help='Verbose mode (%default)')
parser.add_option('-d','--debug',default=False,action='store_true',help='Debug mode (%default)')
(opts,args) = parser.parse_args()
if len(args) < 1:
    parser.print_help()
    sys.exit(0)
input_fnam = args[0]
d1 = datetime.strptime(opts.end,'%Y%m%d')
d0 = d1-timedelta(days=opts.period)

def transform_utm_to_wgs84(easting,northing,utm_zone):
    is_northern = (1 if northing.mean() > 0 else 0)
    utm_coordinate_system = osr.SpatialReference()
    utm_coordinate_system.SetWellKnownGeogCS('WGS84') # Set geographic coordinate system to handle lat/lon
    utm_coordinate_system.SetUTM(utm_zone,is_northern)
    wgs84_coordinate_system = utm_coordinate_system.CloneGeogCS() # Clone ONLY the geographic coordinate system
    utm_to_wgs84_geo_transform = osr.CoordinateTransformation(utm_coordinate_system,wgs84_coordinate_system) # create transform component
    xyz = np.array(utm_to_wgs84_geo_transform.TransformPoints(np.dstack((easting,northing)).reshape((-1,2)))).reshape(easting.shape[0],easting.shape[1],3)
    return xyz[:,:,0],xyz[:,:,1],xyz[:,:,2] # returns lon, lat, altitude

def transform_wgs84_to_utm(longitude,latitude):
    utm_zone = (int(1+(longitude.mean()+180.0)/6.0))
    is_northern = (1 if latitude.mean() > 0 else 0)
    utm_coordinate_system = osr.SpatialReference()
    utm_coordinate_system.SetWellKnownGeogCS('WGS84') # Set geographic coordinate system to handle lat/lon
    utm_coordinate_system.SetUTM(utm_zone,is_northern)
    wgs84_coordinate_system = utm_coordinate_system.CloneGeogCS() # Clone ONLY the geographic coordinate system
    wgs84_to_utm_geo_transform = osr.CoordinateTransformation(wgs84_coordinate_system,utm_coordinate_system) # create transform component
    xyz = np.array(wgs84_to_utm_geo_transform.TransformPoints(np.dstack((longitude,latitude)).reshape((-1,2)))).reshape(longitude.shape[0],longitude.shape[1],3)
    return xyz[:,:,0],xyz[:,:,1],xyz[:,:,2] # returns easting, northing, altitude

if opts.debug:
    plt.interactive(False)
    pdf = PdfPages(opts.fignam)
    fig = plt.figure(1,facecolor='w',figsize=(6,3.5))
    plt.subplots_adjust(top=0.85,bottom=0.20,left=0.15,right=0.90)
    plt.draw()

xstp = 10.0
ystp = -10.0
xmin,xmax,ymin,ymax = (743800.0,756800.0,9236000.0,9251800.0)
xg,yg = np.meshgrid(np.arange(xmin,xmax+0.1*xstp,xstp),np.arange(ymax,ymin-0.1*ystp,ystp))
ngrd = xg.size

ds = gdal.Open(input_fnam)
data = ds.ReadAsArray()
trans = ds.GetGeoTransform()
indy,indx = np.indices(data[0].shape)
lon = trans[0]+(indx+0.5)*trans[1]+(indy+0.5)*trans[2]
lat = trans[3]+(indx+0.5)*trans[4]+(indy+0.5)*trans[5]
xp,yp,zp = transform_wgs84_to_utm(lon,lat)
ds = None # close dataset

tif_tags = {}
with tifffile.TiffFile(input_fnam) as tif:
    for tag in tif.pages[0].tags.values():
        name,value = tag.name,tag.value
        tif_tags[name] = value
    data = tif.pages[0].asarray()
rot = ET.fromstring(tif_tags['65000'])
vh_list = []
dset = []
dtim = []
for i,value in enumerate(rot.iter('BAND_NAME')):
    band = value.text
    sys.stderr.write(band+'\n')
    m = re.search('_(\d+)$',band)
    if not m:
        raise ValueError('Error in finding date >>> '+band)
    vh_list.append(band)
    dh = datetime.strptime(m.group(1),'%Y%m%d')
    if dh < d0:
        continue
    if dh > d1:
        break
    dset.append(griddata((xp.flatten(),yp.flatten()),data[i].flatten(),(xg.flatten(),yg.flatten()),method='nearest'))
    dtim.append(dh)
nh = i+1
if nh != len(data):
    raise ValueError('Error, nh={}, len(data)={}'.format(nh,len(data)))
dset = np.array(dset)
dtim = np.array(dtim)
ntim = date2num(dtim)
t0 = ntim.min()
t1 = ntim.max()
nt = ntim.size
xx = np.arange(t0,t1,0.01)
nx = xx.size
inds = np.arange(nx)
if opts.ind is not None:
    indi = opts.ind
else:
    indi = range(ngrd)

with open(opts.datnam,'w') as fp:
    fp.write('# {:.5f} {:.5f} {:4d}\n'.format(t0,t1,nt))
    fp.write('# {:>5s} {:>4s} '.format('i','ndat'))
    fp.write('{:>11s} {:>11s} {:>4s} '.format('tmin','vmin','fmin'))
    fp.write('{:>11s} {:>11s} {:>4s} '.format('tlft','vlft','flft'))
    fp.write('{:>11s} {:>11s} {:>4s} '.format('trgt','vrgt','frgt'))
    fp.write('{:>13s} {:>13s} '.format('dmin','dstd'))
    fp.write('{:>9s} {:>4s} '.format('tleg','fleg'))
    fp.write('{:>9s} {:>4s} '.format('treg','freg'))
    fp.write('{:>13s} {:>13s} '.format('sstd','scor'))
    fp.write('{:>11s} {:>11s} {:>4s} '.format('traw','vraw','fraw'))
    fp.write('{:>13s} {:>13s} {:>13s} '.format('draw','rstd','rcor'))
    fp.write('{:>13s} {:>13s}\n'.format('bavg','bstd'))
    for i in indi:
        if opts.verbose and i%opts.vint == 0:
            sys.stderr.write('{:8d} {:8d}\n'.format(i,ngrd))
        ndat = 1
        tmin = np.nan
        vmin = np.nan
        fmin = -1
        tlft = np.nan
        vlft = np.nan
        flft = -1
        trgt = np.nan
        vrgt = np.nan
        frgt = -1
        dmin = np.nan
        dstd = np.nan
        tleg = np.nan
        fleg = -1
        treg = np.nan
        freg = -1
        sstd = np.nan
        scor = np.nan
        traw = np.nan
        vraw = np.nan
        fraw = -1
        draw = np.nan
        rstd = np.nan
        rcor = np.nan
        bavg = np.nan
        yi = None
        dtmp = dset[0][i]
        cnd = ~np.isnan(dtmp)
        if cnd.sum() > 0:
            yi = dset[:,i]
        if yi is not None:
            sp = UnivariateCubicSmoothingSpline(ntim,yi,smooth=0.05)
            yy = sp(xx)
            y1 = sp(ntim)
            indx_tmin = np.argmin(yy)
            tmin = xx[indx_tmin]
            vmin = yy[indx_tmin]
            fmin = (1 if indx_tmin == 0 else (2 if indx_tmin == nx-1 else 0))
            yt = yy.copy()
            yt[xx > tmin] = -1.0e10
            indx_tlft = np.argmax(yt)
            tlft = xx[indx_tlft]
            vlft = yy[indx_tlft]
            flft = (1 if indx_tlft == 0 else (2 if indx_tlft == nx-1 else 0))
            yt = yy.copy()
            yt[xx < tmin] = -1.0e10
            indx_trgt = np.argmax(yt)
            trgt = xx[indx_trgt]
            vrgt = yy[indx_trgt]
            frgt = (1 if indx_trgt == 0 else (2 if indx_trgt == nx-1 else 0))
            dmin = vmin-splev([tmin],splrep(ntim,yi,k=1))[0]
            dstd = np.sqrt(np.square(y1-yi).sum()/yi.size)
            cnd0 = (yy >= vmin+dstd)
            cnd = cnd0 & (xx < tmin)
            if cnd.sum() > 0:
                indx_tleg = inds[cnd][-1]
                tleg = xx[indx_tleg]
                vleg = yy[indx_tleg]
                fleg = 0
            else:
                indx_tleg = 0
                tleg = xx[indx_tleg]
                vleg = yy[indx_tleg]
                fleg = 1
            cnd = cnd0 & (xx > tmin)
            if cnd.sum() > 0:
                indx_treg = inds[cnd][0]
                treg = xx[indx_treg]
                vreg = yy[indx_treg]
                freg = 0
            else:
                indx_treg = nx-1
                treg = xx[indx_treg]
                vreg = yy[indx_treg]
                freg = 2
            sstd = np.std(yy)
            scor = np.corrcoef(xx,yy)[0,1]
            indx_traw = np.argmin(yi)
            traw = ntim[indx_traw]
            vraw = yi[indx_traw]
            fraw = (1 if indx_traw == 0 else (2 if indx_traw == nt-1 else 0))
            draw = y1[indx_traw]-vraw
            rstd = np.std(yi)
            rcor = np.corrcoef(ntim,yi)[0,1]
            cnd = np.abs(ntim-tmin) > opts.sigwid
            bavg = np.mean(yi[cnd])
            bstd = np.std(yi[cnd])
        fp.write('{:8d} {:3d} '.format(i,ndat))
        fp.write('{:11.3f} {:13.6e} {:2d} '.format(tmin,vmin,fmin))
        fp.write('{:11.3f} {:13.6e} {:2d} '.format(tlft,vlft,flft))
        fp.write('{:11.3f} {:13.6e} {:2d} '.format(trgt,vrgt,frgt))
        fp.write('{:13.6e} {:13.6e} '.format(dmin,dstd))
        fp.write('{:11.3f} {:2d} '.format(tleg,fleg))
        fp.write('{:11.3f} {:2d} '.format(treg,freg))
        fp.write('{:13.6e} {:13.6e} '.format(sstd,scor))
        fp.write('{:11.3f} {:13.6e} {:2d} '.format(traw,vraw,fraw))
        fp.write('{:13.6e} {:13.6e} {:13.6e} '.format(draw,rstd,rcor))
        fp.write('{:13.6e} {:13.6e}\n'.format(bavg,bstd))
        if opts.debug and not np.isnan(tmin):
            fig.clear()
            ax1 = plt.subplot(111)
            ax1.plot(ntim,yi,'b-')
            ax1.plot(xx,yy,'r-')
            ax1.axhline(bavg,color='c')
            ax1.plot(tmin,vmin-dmin,'g^')
            ax1.plot(traw,vraw+draw,'gv')
            ax1.plot(tmin,vmin,'bo')
            ax1.plot(tlft,vlft,'m<')
            ax1.plot(trgt,vrgt,'m>')
            ax1.plot(tleg,vleg,'c<')
            ax1.plot(treg,vreg,'c>')
            ax1.set_ylim(-30.0,-10.0)
            ax1.set_title('{:d},{:6.2f},{:6.3f},{:6.2f},{:6.3f}'.format(i,sstd,scor,rstd,rcor))
            plt.draw()
            plt.savefig(pdf,format='pdf')
        #break
if opts.debug:
    pdf.close()
