from pathlib import Path

OOM_SCORE_ADJ = Path("/proc/self/oom_score_adj")


def prefer_as_oom_victim(score_file: Path = OOM_SCORE_ADJ) -> None:
    # Under memory pressure the kernel prefers killing a run process over the API process sharing the container.
    # Linux only: elsewhere the file does not exist and the run keeps the default score.
    if score_file.exists():
        score_file.write_text("1000")


def run_isolated(job: dict) -> None:
    # Entry point of a spawned run process. The job arrives as plain data and the engine is imported only here, so the
    # OOM preference is already in place while the analysis libraries load.
    prefer_as_oom_victim()
    from .worker import JobSpec, execute_run

    execute_run(JobSpec.from_dict(job))
