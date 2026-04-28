import psutil

PROTECTED = {"system", "idle", "wininit", "csrss"}

BLOATWARE = [
    "360safe",
    "OneDrive",
    "Skype",
    "Teams",
    "XboxAppServices",
]


class ProcessAgent:

    def status(self) -> list[dict]:
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = proc.info
                processes.append({
                    "name": info["name"],
                    "pid": info["pid"],
                    "cpu": info["cpu_percent"] or 0.0,
                    "ram_mb": (info["memory_info"].rss / (1024 * 1024))
                    if info["memory_info"]
                    else 0.0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        top5 = sorted(processes, key=lambda p: (p["cpu"], p["ram_mb"]), reverse=True)[:5]

        print("\n[ProcessAgent] Top 5 Processes:")
        print(f"  {'Name':<30} {'PID':<8} {'CPU%':<8} {'RAM (MB)'}")
        print(f"  {'-'*60}")
        for p in top5:
            print(f"  {p['name']:<30} {p['pid']:<8} {p['cpu']:<8.1f} {p['ram_mb']:.1f}")

        return top5

    def kill(self, process_name: str) -> float:
        target = process_name.lower()
        memory_freed_mb = 0.0

        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                name = proc.info["name"] or ""
                if name.lower() != target and not name.lower().startswith(target):
                    continue
                if name.lower() in PROTECTED:
                    print(f"[ProcessAgent] Skipping protected process: {name}")
                    continue

                memory_before = (
                    proc.info["memory_info"].rss if proc.info["memory_info"] else 0
                )

                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
                except psutil.AccessDenied:
                    print(f"[ProcessAgent] Access denied: {name} (PID {proc.pid})")
                    continue

                memory_freed_mb = memory_before / (1024 * 1024)
                print(
                    f"[ProcessAgent] Killed {name} | Freed {memory_freed_mb:.1f} MB RAM"
                )
                return memory_freed_mb

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        print(f"[ProcessAgent] Process not found: {process_name}")
        return 0.0

    def optimize(self) -> float:
        total_freed_mb = 0.0
        killed = []

        running = {
            proc.info["name"].lower(): proc
            for proc in psutil.process_iter(["pid", "name", "memory_info"])
            if proc.info.get("name")
        }

        for bloat in BLOATWARE:
            bloat_lower = bloat.lower()
            matched = [
                (name, proc)
                for name, proc in running.items()
                if name.startswith(bloat_lower)
            ]

            for name, proc in matched:
                if name in PROTECTED:
                    continue
                try:
                    memory_before = (
                        proc.info["memory_info"].rss if proc.info["memory_info"] else 0
                    )
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        proc.kill()

                    freed = memory_before / (1024 * 1024)
                    total_freed_mb += freed
                    killed.append((proc.info["name"], freed))
                    print(
                        f"[ProcessAgent] Terminated {proc.info['name']} | Freed {freed:.1f} MB"
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        if killed:
            print(
                f"[ProcessAgent] Optimize complete. "
                f"{len(killed)} process(es) terminated. "
                f"Total freed: {total_freed_mb:.1f} MB RAM"
            )
        else:
            print("[ProcessAgent] No bloatware processes found running.")

        return total_freed_mb
