#!/usr/bin/env bash
# 真实 DEB 生命周期，仅可丢弃 Ubuntu；0=已执行部分成功，1=失败，2=拒绝。
set -euo pipefail
plan= python_bin=python3 disposable=false confirmation=
while (($#)); do
  case "$1" in
    --plan) plan="${2:?}"; shift 2 ;;
    --python) python_bin="${2:?}"; shift 2 ;;
    --disposable-vm) disposable=true; shift ;;
    --confirm-disposable-vm) confirmation="${2:?}"; shift 2 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
if [[ ${GITHUB_ACTIONS:-} != true || ${RUNNER_ENVIRONMENT:-} != github-hosted || ${GITHUB_REPOSITORY:-} != gx0404/ohmyzsh ]]; then
  if [[ $disposable != true || $confirmation != I_UNDERSTAND_THIS_IS_A_DISPOSABLE_VM ]]; then
    printf '%s\n' 'REFUSED: native package lifecycle needs the trusted GitHub-hosted runner or explicit disposable-VM acknowledgement.' >&2
    exit 2
  fi
fi
[[ $(uname -s) == Linux && $(id -u) == 0 && -f $plan ]] || { printf '%s\n' 'Requires native Linux, a plan, and an already privileged orchestrator; no sudo is invoked.' >&2; exit 2; }
for tool in apt-get dpkg dpkg-query dpkg-deb runuser python3; do
  command -v "$tool" >/dev/null || { printf 'Missing prerequisite: %s\n' "$tool" >&2; exit 2; }
done
script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
driver="$script_root/gx_lifecycle.py"
read_field() {
  "$python_bin" -c 'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8"));
for key in sys.argv[2].split("."):
 d=d[key]
print("" if d is None else d)' "$plan" "$1"
}
evidence="$(read_field evidence)"
[[ $plan == "$evidence/plan.json" && $(read_field platform) == ubuntu-amd64 ]] || exit 2
run_as="$(read_field run_as_user)"
[[ -n $run_as && $(id -u "$run_as") != 0 ]] || { printf '%s\n' 'An existing ordinary test account is mandatory.' >&2; exit 2; }
installed_status="$(dpkg-query -W -f='${db:Status-Status}' ohmyzsh-gx 2>/dev/null || true)"
[[ $installed_status != installed ]] || { printf '%s\n' 'Refusing to replace an existing ohmyzsh-gx installation.' >&2; exit 2; }
[[ ! -e /usr/bin/gx-zsh && ! -e /usr/bin/herdr && ! -e /usr/lib/ohmyzsh-gx ]] || { printf '%s\n' 'Package command/layout conflict; no installation attempted.' >&2; exit 2; }
installer="$(read_field initial.installer.path)"
upgrade="$($python_bin -c 'import json,sys; p=json.load(open(sys.argv[1])); print(p["upgrade"]["installer"]["path"] if p["upgrade"] else "")' "$plan")"
home="$(read_field paths.home)"
config="$(read_field paths.config)"
profile="$(read_field paths.profile)"
admin_home="$evidence/package-admin-home"
worker_approval=()
if [[ $disposable == true ]]; then worker_approval=(--disposable-vm --confirm-disposable-vm "$confirmation"); fi
"$python_bin" "$driver" --worker snapshot --plan "$plan" --phase privileged-preflight "${worker_approval[@]}"
chown -R "$(id -u "$run_as"):$(id -g "$run_as")" "$evidence/user" "$evidence/logs" "$evidence/results" "$evidence/snapshots"
chmod a+x "$evidence"
current=install
installed=false
failed=false
checks_file="$evidence/results/linux.json"
"$python_bin" -c 'import json,sys; json.dump({"checks":{},"status":"running","scope":"native DEB lifecycle subset; TUI gates remain pending"},open(sys.argv[1],"w"))' "$checks_file"
record() {
  "$python_bin" -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["checks"][sys.argv[2]]={"status":sys.argv[3],"evidence":sys.argv[4:]}; json.dump(d,open(p,"w"),indent=2)' "$checks_file" "$1" "$2" "${@:3}"
}
run_user() {
  runuser -u "$run_as" -- env -i \
    PATH=/usr/local/bin:/usr/bin:/bin HOME="$home" USER="$run_as" LOGNAME="$run_as" \
    XDG_CONFIG_HOME="$config" XDG_CACHE_HOME="$(read_field paths.cache)" \
    XDG_DATA_HOME="$(read_field paths.data)" XDG_STATE_HOME="$(read_field paths.state)" \
    TMPDIR="$(read_field paths.tmp)" LANG=C.UTF-8 LC_ALL=C.UTF-8 TERM=xterm-256color \
    GITHUB_ACTIONS="${GITHUB_ACTIONS:-}" RUNNER_ENVIRONMENT="${RUNNER_ENVIRONMENT:-}" \
    GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}" "$@"
}
worker() {
  local kind=$1 phase=$2 reference=${3:-}
  local arguments=("$driver" --worker "$kind" --plan "$plan" --phase "$phase" "${worker_approval[@]}")
  [[ -z $reference ]] || arguments+=(--reference "$reference")
  run_user "$python_bin" "${arguments[@]}" > "$evidence/logs/$phase-worker.log" 2>&1
}
package_command() {
  local label=$1; shift
  if [[ $1 == apt-get && ${2:-} == install ]]; then
    env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME="$admin_home" DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 \
      apt-get --simulate "${@:2}" > "$evidence/logs/$label-apt-plan.log" 2>&1
    "$python_bin" -c 'import re,sys; text=open(sys.argv[1],encoding="utf-8").read(); names=re.findall(r"^Inst ([^ :]+)",text,re.M); forbidden=[n for n in names if re.match(r"^(build-essential|gcc|g\+\+|clang|rustc|cargo|zig|cmake)(-|$)",n)]; assert not forbidden, "Refusing compiler/toolchain installation: "+repr(forbidden)' "$evidence/logs/$label-apt-plan.log"
  fi
  env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME="$admin_home" XDG_CONFIG_HOME="$admin_home/config" \
    XDG_CACHE_HOME="$admin_home/cache" DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 \
    "$@" > "$evidence/logs/$label-package.log" 2>&1
}
check_deb() {
  local artifact=$1 label=$2
  dpkg-deb --field "$artifact" Package Architecture Version > "$evidence/logs/$label-metadata.log"
  [[ $(dpkg-deb --field "$artifact" Package) == ohmyzsh-gx && $(dpkg-deb --field "$artifact" Architecture) == amd64 ]]
}
resolve_commands() {
  local label=$1
  run_user /bin/sh -c 'set -eu; test "$(id -u)" -ne 0; command -v gx-zsh; command -v herdr; test "$(command -v gx-zsh)" = /usr/bin/gx-zsh; test "$(command -v herdr)" = /usr/bin/herdr; test "$(readlink -f /usr/bin/gx-zsh)" = /usr/lib/ohmyzsh-gx/bin/gx-zsh; test "$(readlink -f /usr/bin/herdr)" = /usr/lib/ohmyzsh-gx/bin/herdr; herdr --version' > "$evidence/logs/$label-resolution.log" 2>&1
  record command-resolution passed "logs/$label-resolution.log"
}
finish() {
  local status=$?
  trap - EXIT
  if ((status)); then
    failed=true
    printf 'Lifecycle failed at %s; exit=%s\n' "$current" "$status" > "$evidence/logs/linux-error.log"
    record "$current" failed logs/linux-error.log
  fi
  if [[ $installed == true ]]; then
    if ! package_command cleanup apt-get remove -y ohmyzsh-gx; then failed=true; fi
  fi
  "$python_bin" -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["status"]="failed" if sys.argv[2]=="true" else "passed"; json.dump(d,open(p,"w"),indent=2)' "$checks_file" "$failed"
  [[ $failed == false ]] || exit 1
  exit 0
}
trap finish EXIT
worker snapshot preinstall
check_deb "$installer" initial
package_command install apt-get install -y --no-install-recommends "$installer"
installed=true
worker compare postinst-user-unchanged preinstall
record dpkg-no-user-home passed logs/postinst-user-unchanged-preserved.json logs/install-package.log
resolve_commands installed
worker profile installed
record install passed logs/install-package.log logs/installed-cold.stdout.log
current=zsh-pane
worker headless installed
current=herdr-tui
worker tui installed
run_user /bin/sh -c 'printf "\n# lifecycle user edit retained\n" >> "$1"' sh "$profile/.zshrc"
worker snapshot preserve
current=reinstall
package_command reinstall apt-get install -y --no-install-recommends --reinstall "$installer"
worker compare reinstall-preserved preserve
record reinstall passed logs/reinstall-package.log logs/reinstall-preserved-preserved.json
preserve=preserve
if [[ -n $upgrade ]]; then
  current=upgrade
  check_deb "$upgrade" upgrade
  package_command upgrade apt-get install -y --no-install-recommends "$upgrade"
  [[ $(dpkg-query -W -f='${Version}' ohmyzsh-gx) == "$(dpkg-deb --field "$upgrade" Version)" ]]
  worker compare upgrade-preserved preserve
  resolve_commands upgraded
  worker profile upgraded
  worker snapshot preserve-upgraded
  preserve=preserve-upgraded
  record upgrade passed logs/upgrade-package.log logs/upgrade-preserved-preserved.json logs/upgraded-cold.stdout.log
fi
current=uninstall
package_command remove apt-get remove -y ohmyzsh-gx
installed=false
worker compare uninstall-preserved "$preserve"
[[ ! -e /usr/bin/gx-zsh && ! -e /usr/bin/herdr ]]
record uninstall passed logs/remove-package.log logs/uninstall-preserved-preserved.json
record user-data-preserved passed logs/reinstall-preserved-preserved.json logs/uninstall-preserved-preserved.json
current=purge-preserves-user-data
package_command purge dpkg --purge ohmyzsh-gx
worker compare purge-preserved "$preserve"
record purge-preserves-user-data passed logs/purge-package.log logs/purge-preserved-preserved.json
if [[ -n $upgrade ]]; then
  current=install
  package_command candidate-fresh apt-get install -y --no-install-recommends "$upgrade"
  installed=true
  worker compare candidate-postinst-unchanged "$preserve"
  resolve_commands candidate-fresh
  worker profile candidate-fresh
  worker headless candidate-fresh
  current=herdr-tui
  worker tui candidate-fresh
  worker snapshot candidate-preserve
  record install passed logs/candidate-fresh-package.log logs/candidate-fresh-cold.stdout.log
  record dpkg-no-user-home passed logs/candidate-postinst-unchanged-preserved.json logs/candidate-fresh-package.log
  current=reinstall
  package_command candidate-reinstall apt-get install -y --no-install-recommends --reinstall "$upgrade"
  worker compare candidate-reinstall-preserved candidate-preserve
  record reinstall passed logs/candidate-reinstall-package.log logs/candidate-reinstall-preserved-preserved.json
  current=uninstall
  package_command candidate-remove apt-get remove -y ohmyzsh-gx
  installed=false
  worker compare candidate-uninstall-preserved candidate-preserve
  [[ ! -e /usr/bin/gx-zsh && ! -e /usr/bin/herdr ]]
  record uninstall passed logs/candidate-remove-package.log logs/candidate-uninstall-preserved-preserved.json
  current=purge-preserves-user-data
  package_command candidate-purge dpkg --purge ohmyzsh-gx
  worker compare candidate-purge-preserved candidate-preserve
  record purge-preserves-user-data passed logs/candidate-purge-package.log logs/candidate-purge-preserved-preserved.json
fi
