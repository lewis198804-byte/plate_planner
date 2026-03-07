import shutil
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
#---------------------code dealing with backup for recipe DB-----------------------



now = datetime.now(timezone.utc)


jobstore = {
    'default': SQLAlchemyJobStore(url='sqlite:///data/database.db')
}
scheduler = BackgroundScheduler(timezone=timezone.utc)
scheduler.configure(jobstores=jobstore)


def backup_recipe_db():
    con = sqlite3.connect("data/database.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    grabLocation = cur.execute("SELECT backup_location FROM settings")
    locRes = grabLocation.fetchone()
    con.close()
    databasePath = Path("data/database.db")
    try:
        shutil.copy2(databasePath,locRes['backup_location'])
        return True
    except Exception as e:
        print("backup not copied",e)
        return  False

    print("scheduled print command")



def checkBackupDir(directory):
    
    if directory == "":
        return {"resultText": "<span style='color:red'>Directory cannot be empty</span>", "testResult": False}

    homeDir = Path.home()
    dirPath = Path(directory)
    #joinedDir = homeDir.joinpath(dirPath)
    print("submitted directory:",dirPath)
    print("home directory:", Path.home())
    if dirPath.is_dir():
        print("it's a directory")
        try:
            testfile = dirPath.joinpath("testTouch.txt")
            testfile.touch()
            testfile.unlink()
            return {"resultText": f"<span style='color:green'>Can write to this directory</span> home Path: {homeDir} , submitted Path: {dirPath}", "testResult": True}
        except:
            print("no permissions for this directory")
            return {"resultText":"<span style='color:red'>Unable to write to this directory, likely permissions issue</span>", "testResult": False}

        
    else:
        return {"resultText": "<span style='color:red'>Submitted directory is not a directory</span>", "testResult":False}
   

def start_scheduler():

    scheduler.start()
    backupJob = scheduler.get_job("backup_job")
    
    if backupJob.next_run_time < now:
        #backup time has already passed, reset job with new backup time. could have occurred by the program being offline for 
        #extended period of time and missing a backup job. 
        con = sqlite3.connect("data/database.db")
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        grabFreq = cur.execute("SELECT backup_frequency FROM settings")
        freqRes = grabFreq.fetchone()
        scheduler.add_job(backup_recipe_db, "interval", days=freqRes['backup_freq'],id="backup_job", replace_existing=True)
        con.close()
    else:
        pass
        #backup time is in the future so no need to do anything

def turnOffBackups():
    scheduler.remove_all_jobs()
    print("backup job removed")
    if scheduler.running:
        scheduler.shutdown()
        print("scheduler shutdown")
    
def getNextBackupTime():
    backupJob = scheduler.get_job("backup_job")
    return backupJob.next_run_time.ctime()

def turn_on_backups(interval:int,backupDir = ""):
    #check to see if the program has access to the directory that the user has chosen 
    if backupDir != "":
        dirCheck = checkBackupDir(backupDir)
        if dirCheck == True:
            print("can read and write to directory")
            #can make changes to the backup directory
        else:
            print("cant read and write to directory",backupDir)
            #cannot make changes to the directory or it is an invalid directory
    scheduler.add_job(backup_recipe_db, "interval", days=interval,id="backup_job", replace_existing=True)
    if scheduler.state == 0:
        start_scheduler()
    backupJob = scheduler.get_job("backup_job")
    return backupJob.next_run_time
    

    
def schedulerStatus():
    backupJob = scheduler.get_job("backup_job")

    if backupJob is not None:
        con = sqlite3.connect("data/database.db")
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT next_run_time FROM apscheduler_jobs WHERE id = ?",("backup_job",))
        nextRes = cur.fetchone()
        nextBackup = datetime.fromtimestamp(nextRes['next_run_time']).isoformat()
      
        
        con.close()
    else:
        nextBackup = "No Backup scheduled"
    backupDeets = {"scheduler_status": scheduler.state, "next_backup": nextBackup}
    return backupDeets


