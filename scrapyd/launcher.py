import copy
import datetime
import multiprocessing
import sys
from itertools import chain

from twisted.application.service import Service
from twisted.internet import defer, error, protocol, reactor
from twisted.logger import Logger

from scrapyd import __version__
from scrapyd.exceptions import LauncherError
from scrapyd.interfaces import IEnvironment, IJobStorage, IPoller

log = Logger()


def get_crawl_args(message):
    """Return the command-line arguments to use for the scrapy crawl process
    that will be started for this message
    """
    copied = message.copy()
    del copied["_project"]

    return [
        copied.pop("_spider"),
        *chain.from_iterable(["-s", f"{key}={value}"] for key, value in copied.pop("settings", {}).items()),
        *chain.from_iterable(["-a", f"{key}={value}"] for key, value in copied.items()),  # spider arguments
    ]


def get_launch_message(message):
    """Return the job's launch parameters, in the same shape as the pending jobs in the listjobs.json response.

    The keys that identify a job (``name``, ``_job``, ``_project``, ``_spider``, ``_version`` and ``settings``) are
    kept out of ``args``, mirroring ListJobs.render_GET() for pending jobs.

    The snapshot is taken before the launcher merges its own settings (LOG_FILE, FEEDS, JOBDIR) into the message, so
    that the parameters match what was submitted to the schedule.json webservice and stored in the spider queue. A
    deep copy is returned, since the message's nested settings dict is mutated in place afterwards.
    """
    return copy.deepcopy(
        {
            "version": message.get("_version"),
            "settings": message.get("settings", {}),
            "args": {
                key: value
                for key, value in message.items()
                if key not in ("name", "_job", "_project", "_spider", "_version", "settings")
            },
        }
    )


class Launcher(Service):
    name = "launcher"

    def __init__(self, config, app):
        self.processes = {}
        self.finished = app.getComponent(IJobStorage)
        self.max_proc = self._get_max_proc(config)
        self.runner = config.get("runner", "scrapyd.runner")
        self.app = app

    def startService(self):
        log.info(
            "Scrapyd {version} started: max_proc={max_proc!r}, runner={runner!r}",
            version=__version__,
            max_proc=self.max_proc,
            runner=self.runner,
            log_system="Launcher",
        )
        for slot in range(self.max_proc):
            self._get_message(slot)

    def _get_message(self, slot):
        poller = self.app.getComponent(IPoller)
        poller.next().addCallback(self._spawn_process, slot)
        log.debug("Process slot {slot} ready", slot=slot)

    def _spawn_process(self, message, slot):
        project = message["_project"]
        environment = self.app.getComponent(IEnvironment)
        # Snapshot the submitted parameters before merging the environment's settings, to match the pending queue.
        launch = get_launch_message(message)
        message.setdefault("settings", {})
        message["settings"].update(environment.get_settings(message))

        env = environment.get_environment(message, slot)
        args = [sys.executable, "-m", self.runner, "crawl", *get_crawl_args(message)]

        process = ScrapyProcessProtocol(project, message["_spider"], message["_job"], env, args, launch=launch)
        process.deferred.addBoth(self._process_finished, slot)

        try:
            reactor.spawnProcess(process, sys.executable, args=args, env=env)
        except OSError as e:
            raise LauncherError(f"{e}: args={args!r}") from e

        self.processes[slot] = process
        log.debug("Process slot {slot} occupied", slot=slot)

    def _process_finished(self, _, slot):
        process = self.processes.pop(slot)
        process.end_time = datetime.datetime.now()
        self.finished.add(process)
        log.debug("Process slot {slot} vacated", slot=slot)

        self._get_message(slot)

    def _get_max_proc(self, config):
        max_proc = config.getint("max_proc", 0)
        if max_proc:
            return max_proc

        try:
            cpus = multiprocessing.cpu_count()
        except NotImplementedError:  # Windows 17520a3
            cpus = 1
        return cpus * config.getint("max_proc_per_cpu", 4)


# https://docs.twisted.org/en/stable/api/twisted.internet.protocol.ProcessProtocol.html
class ScrapyProcessProtocol(protocol.ProcessProtocol):  # noqa: PLW1641 missing __hash__ method
    def __init__(self, project, spider, job, env, args, launch=None):
        self.project = project
        self.spider = spider
        self.job = job
        self.pid = None
        self.start_time = datetime.datetime.now()
        self.end_time = None
        self.args = args
        self.env = env
        # The launch parameters (version, settings, spider args), in the shape of the listjobs.json pending jobs.
        # Absent for jobs created by code that predates parameter persistence, including rows in old databases.
        self.launch = {"version": None, "settings": {}, "args": {}} if launch is None else launch
        self.deferred = defer.Deferred()

    # For equality assertions in tests.
    def __eq__(self, other):
        return (
            self.project == other.project
            and self.spider == other.spider
            and self.job == other.job
            and self.pid == other.pid
            and self.start_time == other.start_time
            and self.end_time == other.end_time
            and self.args == other.args
            and self.env == other.env
            and self.launch == other.launch
        )

    # For error messages in tests.
    def __repr__(self):
        return (
            f"ScrapyProcessProtocol(project={self.project} spider={self.spider} job={self.job} pid={self.pid} "
            f"start_time={self.start_time} end_time={self.end_time} args={self.args} env={self.env} "
            f"launch={self.launch})"
        )

    def outReceived(self, data):
        log.info(data.rstrip(), log_system=f"Launcher,{self.pid}/stdout")

    def errReceived(self, data):
        log.error(data.rstrip(), log_system=f"Launcher,{self.pid}/stderr")

    def connectionMade(self):
        self.pid = self.transport.pid
        self.log("info", "Process started:")

    # https://docs.twisted.org/en/stable/core/howto/process.html#things-that-can-happen-to-your-processprotocol
    def processEnded(self, status):
        if isinstance(status.value, error.ProcessDone):
            self.log("info", "Process finished:")
        else:
            self.log("error", f"Process died: exitstatus={status.value.exitCode!r}")
        self.deferred.callback(self)

    def log(self, level, action):
        getattr(log, level)(
            "{action} project={project!r} spider={spider!r} job={job!r} pid={pid!r} args={args!r}",
            action=action,
            project=self.project,
            spider=self.spider,
            job=self.job,
            pid=self.pid,
            args=self.args,
        )
