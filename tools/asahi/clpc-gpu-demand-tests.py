#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only OR MIT
"""Run production CLPC demand/hold logic with controlled PMGR reads and time."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def item(text, signature):
    start = text.index(signature)
    begin = text.index('{', start)
    depth, end = 1, begin + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def main():
    source = (ROOT / 'drivers/soc/apple/clpc.c').read_text()
    header = (ROOT / 'include/linux/soc/apple/pmc.h').read_text()
    rail_shift = re.search(r'^#define APPLE_PMC_RAIL_SHIFT\(rail\).*$', header, re.M).group(0)
    types = '\n'.join(item(source, s) + ';' for s in [
        'struct apple_clpc_hw {', 'struct apple_clpc_vote {'])
    tables = '\n'.join(item(source, 'static const struct apple_clpc_hw ' + n) + ';'
                       for n in ['apple_clpc_hw_t8132', 'apple_clpc_hw_t8140', 'apple_clpc_hw_t6040'])
    methods = '\n'.join(item(source, s) for s in [
        'static unsigned int apple_clpc_vote(', 'static u32 apple_clpc_floor(',
        'static void apple_clpc_sample('])
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define APPLE_CLPC_LEVELS 4
#define APPLE_CLPC_HOLD_MS 32
#define HZ 1000
#define max(a,b) ((a) > (b) ? (a) : (b))
#define GENMASK(h,l) (((1u << ((h)-(l)+1))-1) << (l))
#define APPLE_PMC_RAIL_SHIFT(r) ((r)*8)
#define time_after_eq(a,b) ((long)((a)-(b)) >= 0)
#define msecs_to_jiffies(ms) (ms)
enum apple_clpc_rail { APPLE_CLPC_DCS, APPLE_CLPC_SOC, APPLE_CLPC_RAILS };
''' + types + r'''
struct apple_clpc_cluster { unsigned int request[APPLE_CLPC_RAILS]; };
struct apple_clpc {
 const struct apple_clpc_hw *hw;
 struct apple_clpc_cluster clusters[1];
 struct apple_clpc_vote vote[APPLE_CLPC_RAILS];
 unsigned int nr_clusters, agent;
 unsigned long samples, next_scan, update_errors;
 void *covered, *pmc, *gpu_pmgr;
 u32 gpu_offset, mask;
};
static unsigned long jiffies;
static void *cpu_possible_mask;
static u32 pmgr_status, published;
static int read_error, vote_error;
static bool queued_idle;
static bool cpumask_equal(void *a, void *b) { return a == b; }
static void apple_clpc_find_clusters(struct apple_clpc *c) { (void)c; }
static void apple_clpc_sample_cluster(struct apple_clpc *c, struct apple_clpc_cluster *cl) { (void)c; (void)cl; }
static int regmap_read(void *map, u32 offset, u32 *status) {
 assert(map); (void)offset; *status=pmgr_status; return read_error;
}
static int apple_pmc_floor_update(void *pmc, unsigned int agent, u32 mask, u32 floor) {
 (void)pmc; assert(agent==1 && mask==3); published=floor; return vote_error;
}
static void apple_clpc_queue(struct apple_clpc *c, bool idle) { (void)c; queued_idle=idle; }
''' + tables + '\n' + methods + r'''
static void check(const struct apple_clpc_hw *hw, u32 top) {
 struct apple_clpc c={.hw=hw,.agent=1,.mask=3,.gpu_pmgr=hw->gpu_demand ? (void *)1 : NULL};
 jiffies=0; read_error=vote_error=0; pmgr_status=0; published=~0u;
 apple_clpc_sample(&c); assert(published==0 && queued_idle);
 jiffies=100; pmgr_status=0xf0;
 apple_clpc_sample(&c); assert(published==top && !queued_idle);
 pmgr_status=0;
 jiffies=131; apple_clpc_sample(&c); assert(published==top && !queued_idle);
 jiffies=132; apple_clpc_sample(&c); assert(published==0 && queued_idle);
 // A partially powered state is not a powered graphics consumer.
 jiffies=200; pmgr_status=0xe0;
 apple_clpc_sample(&c); assert(published==0 && queued_idle);
 // Preserve the qualified floor when a live demand input cannot be sampled.
 read_error=-EIO; apple_clpc_sample(&c); assert(published==top);
 read_error=0; jiffies=232;
 apple_clpc_sample(&c); assert(published==0);
 // GPU activity must not erase independent CPU demand at release.
 c.nr_clusters=1; c.clusters[0].request[0]=2; c.clusters[0].request[1]=1;
 jiffies=300; pmgr_status=0xf0; apple_clpc_sample(&c); assert(published==top);
 jiffies=332; pmgr_status=0; apple_clpc_sample(&c); assert(published==0x12);
 vote_error=-EIO; apple_clpc_sample(&c); assert(c.update_errors==1);
}
int main(void) {
 check(&apple_clpc_hw_t6040,0x25);
 check(&apple_clpc_hw_t8140,0x34);
 check(&apple_clpc_hw_t8132,0x35);
 puts("PASS: T6040 5/2, T8140 4/3 and T8132 5/3 GPU floors; 32 ms idle release; partial state, read failure, CPU demand and vote-error controls");
}
'''
    code = code.replace('#define APPLE_PMC_RAIL_SHIFT(r) ((r)*8)', rail_shift)
    with tempfile.TemporaryDirectory(prefix='apple-clpc-gpu-') as tmp:
        root = Path(tmp)
        for name, text in [
            ('fixed', code),
            ('omit-gpu-demand', code.replace('if (clpc->gpu_pmgr) {', 'if (false) {')),
            ('release-too-early', code.replace('msecs_to_jiffies(APPLE_CLPC_HOLD_MS)', '0')),
            ('retain-at-idle', code.replace('vote->state = 0;', '')),
        ]:
            path = root / (name + '.c')
            path.write_text(text)
            binary = path.with_suffix('')
            subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Wextra',
                            '-Werror', str(path), '-o', str(binary)], check=True)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            if name == 'fixed':
                assert run.returncode == 0, run.stderr
                print(run.stdout.strip())
            else:
                assert run.returncode != 0, name
                print('PASS negative control:', name)


if __name__ == '__main__':
    main()
