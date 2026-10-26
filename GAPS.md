# T6040 GPU parity audit

Audit baseline: `integration/aurora` at
`9cbdd0734d9e`, with GPU integration #463 (`a0a9485847f8`), the
r5 display series (`905dff774561`), camera #462 (`2114ed0c6245`), and the
two r6 display patches. The reconstructed r6 branch is
`wip/j616s-display-r6` at `af0a664046fb`.

This series repairs regression coverage. It does not change clock, voltage,
firmware policy, feature advertisement, or the submission algorithm. The major
T6040 calibration and image-admission changes requested by this audit are
already in the baseline. Software parity does not establish benchmark or CTS
parity. There are no J616s results for this series yet.

## Gap table

| Gap | Neo behavior | T6040 before this series | After this series | Evidence / remaining gate |
| --- | --- | --- | --- | --- |
| Per-chip leakage and power ceiling | T8140 has its own platform data | #463 requires a versioned DT handoff, finite positive leakage, a power ceiling and the measured core mask; no single-unit fallback | Same runtime behavior | `g17/calibration.rs`, `g17/initdata/v25g83.rs`; #463 commits `a8fb1380b414`, `53877eaebd4b`, `415fd2e6ee2d` |
| Raw OPP count versus logical states | Firmware consumes 11 logical states | 16 raw GPU OPPs; 11 selectors in each A/B map; both end at raw OPP 15; unused handoff slots must be zero | KUnit now uses valid complete maps and checks the final state's second voltage lane | `g17/calibration.rs`; a count of 15 in an ADT property is not evidence for expanding this firmware layout |
| Full clock eligibility | Platform OPPs feed firmware performance tables | DT supplies both cluster voltages and GPU/CS/AFR frequencies; maps and relative-B are checked against the GPU OPP table | Same runtime behavior | `g17/initdata/v25g83.rs`, `g17/fw/initdata/v25g83.rs`; confirm sustained clocks and limiting reasons on hardware |
| DVFS ramp / effort | Full effort on publication, cleared after 16 ms of continuous idle | Same `Firmware::note_submission`, direct-port accounting and race-checked idle clear | Same runtime behavior | `g17/mod.rs`, `g17/port.rs`, `g17/power.rs`; opaque firmware power words are not a documented ramp control |
| Idle / off policy | Shared host hold and firmware device-control path | Same host implementation; source documents a 25G83 effective 2 ms off delay and approximately 1 ms wake cost | Same runtime behavior; default hold unchanged | `g17/power.rs`; measure actual idle/wake latency before altering policy |
| Fast-die / PMP | Platform-specific firmware power graph | 25G83 AON table and separate power-state target/release (101/96 C) are already populated; DT enables the GFX suppliers | Same runtime behavior | `g17/fw/initdata/v25g83.rs::POWER_STATE_WORDS`, `g17/initdata/v25g83.rs`, J616s DT; verify clocks with PMP running |
| Periodic preemption | Context-switch timer mask is zero | Same zero mask; two-cluster operand-state allocation differs by hardware layout | Same runtime behavior | `g17/fw/initdata.rs::CONTEXT_SWITCH_TIMER_MASK`, `g17/fw/compute.rs::OperandState`; no evidence supports changing the mask |
| High-priority queues | HIGH / MEDIUM / LOW firmware scheduling profiles | Same scheduling-policy selector and priority work rings | Same runtime behavior | `g17/mod.rs::scheduling_policy`, `g17/fw/channels.rs`, `g17/qos.rs` |
| Timestamp publication | Retains one CPU mapping for each firmware timestamp buffer | Same shared timestamp buffer and completion publication | Host timestamp suite again compiles and executes the production retained-mapping writer | `timestamp.rs`, `mmu.rs::TimestampVmap`, `tools/testing/selftests/drivers/gpu/asahi-m4/test-timestamps.py` |
| Statistics | Drains firmware statistics; no `agx_stats` snapshot | Same; `stats_snapshot()` returns `None` on both | Same runtime behavior | `g17/channel.rs`, `g17/runtime/events.rs`, `g17/mod.rs`; statistics decoding/export remains a shared limitation |
| Alternate loaded image | T8140 uses fixed firmware selection | Both exact T6040 normalized TEXT digests are admitted in one `Build.images` slice | Same runtime behavior | #453 (`26f5eb68dbce`), #463 (`804bba86ca55`), `hw/t6040.rs`, `g17/fw/variant.rs`, `fwid.rs`; unknown images remain refused |
| Submission/completion improvements | #423 shared G17 runtime | #423 is already an ancestor of the baseline; direct compute/render publication, admission domains and completion collection are shared | Same runtime behavior | #423; `g17/runtime.rs`, `g17/runtime/render/direct.rs`, `g17/port.rs`, `g17/completion.rs` |
| G13/G14 `submit.empty` regressions | Neo uses the G17 runtime | G16S uses that same G17 runtime, not the maintained G13/G14 workqueue | Same runtime behavior | `driver.rs`, `file.rs`, `g17/queue/mod.rs`; user-space empty submits may never reach this ioctl; trace and benchmark the paired Mesa stack |
| G13/G14 idle wake regressions | Firmware-specific cost plus shared host overhead | G16S shares common ioctl/GEM/sync infrastructure, but has different firmware, power handling and queue backend | Same runtime behavior | `driver.rs`, `g17/power.rs`; G13/G14 benchmark ratios cannot be transferred to G16S |
| QID capacity | Firmware floor 0; reserve protects dedicated render pairs | 25G83 reserves QIDs 0..31; public queue limit is reduced accordingly | KUnit checks floor 32 in dynamic growth and full logical queue budget tests; host resource runner follows current reserve helper | `g17/kick.rs`, `g17/runtime.rs`, `tools/asahi/g17-resource-tests.py` |
| Compute ownership / retained mappings | Recovery and retirement witnesses protect mapping lifetime | Same production queue ownership, source loans, growth rollback and deferred release | Restored host fixtures and negative controls; source loans explicitly prevent premature reuse/sharing/rearming | `tools/asahi/g17-capacity-fault-tests.py`, constructor/growth/pool/release-order fixtures |
| Restart and fault classification | Shared recovery handshake plus validated T8140 per-slot keys | Shared handshake uses 25G83 status offsets; `recovery_slot_keys=None` preserves firmware blame when keys are unknown | Same runtime behavior | `hw/t6040.rs`, `g17/initdata.rs`, `g17/recovery/attribution.rs`; successful 25G83 fault/restart qualification is still required |
| DART / UAT | Shared mapping ownership and checked page-table borrowing | Shared MMU, with T6040 reserved tables, PoC cleaning, per-page TLBI and native GPU permission quirks | Same runtime behavior | `hw/t6040.rs`, `mmu.rs`, `pgtable.rs`; do not remove coherency or handoff requirements for a benchmark |
| Memory accounting | Creator-attributed committed/resident GEM accounting and capacity admission | Same `memacct::Client`, `File::memory_stats` and shared capacity machinery | Same runtime behavior | `file.rs`, `gem.rs`, `memacct.rs`, `g17/capacity.rs`; verify multi-client high-water and post-close behavior on hardware |
| MCache / few-primitives / ray traversal | Enabled by the 26A428 variant | Disabled by 25G83 variant; source records hangs for few-primitives and stalled ray traversal, while MCache is unqualified | Same runtime behavior | `g17/fw/variant.rs::V25G83`; enabling these requires independent ABI evidence and hardware tests |
| M5 Pro comparison | No M5 Pro hardware configuration exists in this public baseline | No T605x/G17S KMD path to compare | No claim of M5 parity | Pinned public tree contains T6040 and T8140; a licensed public M5 Pro reference is required |
| CTS and Linux/macOS performance ratio | Hardware results belong to their exact kernel/Mesa pair | No result for this candidate | Pending hardware agent | Run gpubench with matching suite, configuration and conditions; review CTS failures and kernel faults before claiming parity |

## Source and validation boundaries

The implementation references are the licensed public Aurora/Asahi kernel and
loader history. Existing Gravity Linux-derived layouts and attribution remain
unchanged. The public Gravity Linux `gravity-m4` reference inspected at
`4fc326f6c25ccceb7515e2635c22e01fde5d3bac` was checked in `g16.rs`,
`g16_runtime.rs` and `g16_power.rs`. Those files do not supply validated
T6040 recovery slot keys; that G16 runtime explicitly leaves compute
non-preemptible. No private implementation, firmware bytes, voltage table or
lab record is included here.

The build handoff must identify the exact tested source and loader, verify boot
payload checksums, retain r6g rollback, and distinguish CPU/QEMU tests from GPU
execution. Missing J616s measurements are not passing results.
