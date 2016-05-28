from sys import path
path.append('/work/rqiao/HFdata/mewp')

from mewp.simulate.wrapper import PairAlgoWrapper
from mewp.simulate.runner import PairRunner
from mewp.math.simple import SimpleMoving

import matplotlib
import matplotlib.pylab as plt
import itertools
import pickle
import sys
import os

import numpy as np
import pandas as pd
import datetime as dt
from numpy import cumsum, log, sqrt, std, subtract
from Queue import Queue
%matplotlib inline
from mewp.util.futures import get_day_db_path

from mewp.reader.futuresqlite import SqliteReaderDce, SqliteReaderL1
from mewp.data.frame import *
from sqlite3 import OperationalError
from my_utils import get_trade_day, contract_backtest, get_price_diff
DATA_PATH = '/work/rqiao/HFdata/dockfuture'


class Moving(object):
    ##constructor
    # @param size of moving window
    def __init__(self, size, sigma_size):
        self.size = size
        self.sigma_size = sigma_size
        self.queue = Queue()
        self.sigma_queue = Queue()
        self.sums = 0
        self.mean = 0
        self.powersum = 0
        self.var = 0
        self.std = 0

    ## add a new observation
    # @param observe new observation
    # @param mean mean at that moment
    def add(self,observe):
        self.sums += observe
        self.queue.put(observe)
        self.sigma_queue.put(observe)
        while self.queue.qsize() > self.size:
            popped = self.queue.get()
            self.sums -= popped
        self.mean = self.sums / self.queue.qsize()
        self.sigma_queue.put(observe-self.mean)
        self.powersum += (observe - self.mean) ** 2
        while self.sigma_queue.qsize() > self.sigma_size:
            popped = self.sigma_queue.get()
            self.powersum -= popped ** 2
        self.var = self.powersum / self.sigma_queue.qsize()
        self.sd = sqrt(self.var)

    # return the standard deviation
    # @param mean mean for this moment
    def get_std(self):
        return self.std

    def get_mean(self):
        return self.mean

## pair trading with stop win
# Max position within 1
class MyAlgo(PairAlgoWrapper):

    # called when algo param is set
    def param_updated(self):
        # make sure parent updates its param
        super(MyAlgo, self).param_updated()
        # create rolling
        self.long_roll = Moving(size = self.param['rolling'], sigma_size = self.param['rolling_sigma'])
        self.short_roll = Moving(size = self.param['rolling'], sigma_size = self.param['rolling_sigma'])
        self.sd_coef = self.param['sd_coef']
        self.block = self.param['block']
        self.stop_win = self.param['stop_win']

        #other params
        self.last_long_res = -999
        self.last_short_res = -999


    def on_tick(self, multiple, contract, info):
        # skip if price_table doesnt have both, TODO fix this bug internally
        if len(self.price_table.table) < 2:
            return

        # get residuals and position
        long_res = self.pair.get_long_residual()
        short_res = self.pair.get_short_residual()
        pos = self.position_y()

        # update rolling
        self.long_roll.add(long_res)
        self.short_roll.add(short_res)
        long_mean = self.long_roll.get_mean()
        short_mean = self.short_roll.get_mean()
        long_std = self.long_roll.get_std()
        short_std = self.short_roll.get_std()

        # stop short position
        if pos == -1:
            if long_res + self.last_short_res >= self.stop_win:
                self.long_y(y_qty = 1)

        # stop long position
        if pos == 1:
            if short_res + self.last_long_res >= self.stop_win:
                self.short_y(y_qty = 1)
        else:

            # action only when unblocked: bock size < rolling queue size
            if self.long_roll.queue.qsize() > self.block:
                # long when test long_res > autoreg.mean+sd_coef*roll.sd
                if long_res > long_mean + self.sd_coef * long_std:
                    # only long when position is 0 or -1
                    if pos <= 0:
                        self.long_y(y_qty=1)
                        self.last_long_res = long_res

                # short when test short_res > autoreg.mean+sd_coef*roll.sd
                elif short_res > short_mean + self.sd_coef * short_std:
                     # only short when position is 0 or 1
                    if pos >= 0:
                        self.short_y(y_qty=1)
                        self.last_short_res = short_res
                else:
                    pass
    def on_daystart(self, info):
        pass

pair = ['c1505', 'c1509']
date_list = get_trade_day(pair)
algo = { 'class': MyAlgo }
algo['param'] = {'x': pair[0],
                 'y': pair[1],
                 'a': 1,
                 'b': 0,
                 'rolling': 4000,
                 'rolling_sigma': 4000,
                 'sd_coef': 3,
                 'block': 100,
                 'stop_win': 200,
                 }
settings = { 'date': date_list,
             'path': DATA_PATH,
             'tickset': 'top',
             'algo': algo}

runner = PairRunner(settings)
runner.run()
account = runner.account
history = account.history.to_dataframe(account.items)
score = float(history[['pnl']].iloc[-1])
runner = PairRunner(settings)
rolling_list = range(1000,20000,2000)
rolling_sigma_list = range(1000,20000,2000)
sd_coef_list = np.arange(2,8,0.5)
stop_win_list = range(1,10)
final_profit = []
for r in rolling_list :
    for rs in rolling_sigma_list:
        for sd in sd_coef_list :
            for sw in stop_win_list:
                runner.run(algo_param={'rolling': r, 'rolling_sigma': rs, 'sd_coef': sd, 'stop_win': sw })
                final_profit.append(float(history[['pnl']].iloc[-1]))
pars = list(itertools.product(rolling_list, rolling_sigma_list, sd_coef_list, stop_win_list))
result = pd.DataFrame({"rolling": [p[0] for p in pars],
                       "rolling_sigma": [p[1] for p in pars],
                       "sd_coef": [p[2] for p in pars],
                       "stop_win": [p[3] for p in pars]
                       "PNL": [float(f) for f in final_profit]})
                       import pickle
pickle.dump(result, open( "c_stopwin_result.p", "wb" ) )
