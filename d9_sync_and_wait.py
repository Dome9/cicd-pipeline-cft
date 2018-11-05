# 3rd party libraries
import boto3    # $ pip install boto3
import requests # $ pip install requests

# python standard libraries
import csv
import datetime
import json
import time
import dateutil.parser
import argparse


def d9_sync_and_wait(d9keyId, d9secret, awsAccNumber, region, stackName, excludedTypes, maxTimeoutMinutes=10, awsprofile=''):
    
    # Take start time
    t0 = datetime.datetime.utcnow()
    print ("\n\n{}\nStarting...\n{}\n\nSetting now (UTC {}) as base time".format(80*'*', 80*'*' ,t0))
    (d9_supported_cfn_types,d9_non_supported_cfn,relevant_dome9_types) = calc_relevant_stack_types(awsAccNumber, region, stackName, excludedTypes, awsprofile)
    
    # Perform SyncNow
    perfrom_sync_now(awsAccNumber,d9keyId,d9secret)
    #time.sleep(5) # (optional) wait a few seconds to let the system opportunity to fetch entities

    # Query Fetch status api, loop until ready
    while True:
        api_status = query_fetch_status(awsAccNumber,region,relevant_dome9_types,d9keyId,d9secret)
        result = analyze_entities_update_status(relevant_dome9_types, api_status, t0)
        result.print_me()
        if(result.isAllCompleted()):
            break
        tNow = datetime.datetime.utcnow()
        elapsed =  (tNow-t0).total_seconds()
        if elapsed > maxTimeoutMinutes * 60:
            print('\nStopping script, passed maxTimeoutMinutes ({})'.format(maxTimeoutMinutes))
            break
        else:
            print('\nNot done yet. Will sleep a bit and poll the status again...')
            time.sleep(30)
    
    # transform and return data set
    result.nonSupportedCFTTypes = d9_non_supported_cfn
    return result

def analyze_entities_update_status(requested_dome9_types, status, t0):
    retObj = StatusResult()
    for d9type in requested_dome9_types:
        filteredList = [elem for elem in status if elem['entityType']==d9type ]
        ser_status = next(iter(filteredList), None)
        if(not ser_status):
            retObj.pending.append(d9type)
        else:
            tEntity = dateutil.parser.parse(ser_status['lastSuccessfulRun']).replace(tzinfo=None) # sadly datetime.datetime.utcnow() is not timzeone aware so I'm removing the TZ so we can compare them
            if tEntity>t0:
                retObj.completed.append(d9type)
            else:
                retObj.pending.append(d9type)
    
    return retObj

def perfrom_sync_now(awsAccNumber,d9keyId,d9secret):
    #replace awsaccount number with Dome9 cloud account Id
    print('\nresolving Dome9 account id from aws account number: {}'.format(awsAccNumber))
    r = requests.get('https://api.dome9.com/v2/cloudaccounts/{}'.format(awsAccNumber), auth=(d9keyId,d9secret))
    d9Id = r.json()['id']
    print('Found it. Dome9 cloud account Id={}'.format(d9Id))
    
    # now perform sync now
    print('\nSending Dome9 SyncNow command...')
    r = requests.post('https://api.dome9.com/v2/cloudaccounts/{}/SyncNow'.format(d9Id), auth=(d9keyId,d9secret))
    r.raise_for_status() # throw an error if we did not get an OK result
    resp =  r.json()
    print(resp)
    
    return

def query_fetch_status(awsAccNumber,region,relevant_dome9_types ,d9keyId, d9secret):
    print('Querying entities fetch status from Dome9 API...')
    r = requests.get('https://api.dome9.com/v2/EntityFetchStatus?externalAccountNumber={}'.format(awsAccNumber), auth=(d9keyId,d9secret))
    resp =  r.json()
    d9region = region.replace('-','_') # dome9 identifies regions with underscores
    relevant =  filter(lambda entry: entry['region'] in [d9region,''] ,
                filter(lambda entry: entry['entityType'] in relevant_dome9_types,
                resp))
    return relevant

def calc_relevant_stack_types(awsAccNumber, region, stackName, excludedTypes, awsprofile):
    MAPPINGS_PATH = "./cfn_mappings.csv"
    # allow to specify specific profile, fallback to standard boto credentials lookup strategy https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html
    aws_session = boto3.session.Session(profile_name=awsprofile, region_name=region) if awsprofile else boto3.session.Session(region_name=region) 
    
    # sanity test - verify that we have credentials for the relevant AWS account numnber
    sts = aws_session.client('sts')
    account_id = sts.get_caller_identity()["Account"]
    if(awsAccNumber != account_id):
        print('Error - the provided awsAccNumber ({}) is not tied to the AWS credentials of this script ({}) consider providing a different "profile" argument'.format(awsAccNumber,account_id ))
        exit(2)
    
    cfn = aws_session.client('cloudformation')
    response = cfn.list_stack_resources(
        StackName=stackName,
        # NextToken='string' # TODO handle pagination
    )
    relevant_cfn_types = list(set([i['ResourceType'] for i in response['StackResourceSummaries']])) # set will make it unique
    print_list(relevant_cfn_types,'CFN types found in this stack')

    # get dome9 types from mapping file
    cfn_mappings = dict()
    with open(MAPPINGS_PATH, "rb") as f:
        reader = csv.DictReader(f)
        for item in reader:
            if item['Dome9']:
                cfn_mappings[item['CFN']] = item['Dome9'].split(',')
    
    d9_supported_cfn_types = [cfn for cfn in relevant_cfn_types if cfn in cfn_mappings]
    print_list(d9_supported_cfn_types,"relevant CFN types SUPPORTED by Dome9")
    
    d9_non_supported_cfn = [cfn for cfn in relevant_cfn_types if not cfn in cfn_mappings]
    print_list(d9_non_supported_cfn,"relevant CFN types NOT supported by Dome9")

    relevant_dome9_types = set(flatten([ cfn_mappings[cfn] if cfn in cfn_mappings else list([]) for cfn in relevant_cfn_types]))
    #print_list(relevant_dome9_types,'relevant Dome9 Data fetcher types')

    actual_d9_types = [t for t in relevant_dome9_types if not t in excludedTypes]
    print_list(actual_d9_types, "Actual Dome9 types to wait for")
    print_list(excludedTypes,"Excluded types (will not wait for them)")

    return (d9_supported_cfn_types,d9_non_supported_cfn,actual_d9_types)

# Utility methods

def print_list(list,name):
    if(name):
        header =  '{} ({}):'.format(name, len(list))
        print ('\n{}\n{}'.format(header,len(header)*'-'))
    print ('\n'.join(list))

def flatten(l): 
    return [item for sublist in l for item in sublist]


class StatusResult:
    def __init__(self):
        self.completed = []
        self.pending = []
    
    def isAllCompleted(self):
        return len(self.pending) == 0

    def print_me(self):
        print_list(self.completed,"Completed")
        print_list(self.pending,"Pending")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--d9keyId', required=True, type=str)
    parser.add_argument('--d9secret', required=True, type=str)
    parser.add_argument('--awsCliProfile', required=False, type=str)
    parser.add_argument('--awsAccountNumber', required=True, type=str)
    parser.add_argument('--region', required=True, type=str)
    parser.add_argument('--stackName', required=True, type=str)
    parser.add_argument('--excludedTypes', required=False, type=str)
    parser.add_argument('--maxTimeoutMinutes', required=False, type=int, default=10)
    args = parser.parse_args()
    excludedTypes = args.excludedTypes.split(',') if args.excludedTypes else []  #  ['LogGroups'] # these are types which are not yet supported by sync now and are not critical for our GSL rules. (in this case LogGroups is not even a GSL entity)
    t1 = datetime.datetime.utcnow()

    st = d9_sync_and_wait(awsAccNumber=args.awsAccountNumber, region = args.region, stackName=args.stackName, 
        excludedTypes = excludedTypes, maxTimeoutMinutes=args.maxTimeoutMinutes, 
        awsprofile=args.awsCliProfile, d9keyId=args.d9keyId, d9secret=args.d9secret)
    
    t2 = datetime.datetime.utcnow()
    print('Script ran for {} seconds'.format((t2-t1).total_seconds()))
    if (st.isAllCompleted()):
        print("\n*** All supported services were successfully updated (fetched) ***\n")
        exit(0)
    else:
        print('not all types were updated. Please consider to increase the script timeout or to exclude these types from being wait upon: {}'.format(",".join(st.pending)))
        exit(1)



# TODO 1 allow 2nd run without triggering a sync now and with accepting the previous time as base time.
# TODO 2 support CFT list-stack-resources pagination