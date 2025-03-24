import json
import boto3
import os
import logging
import random
import string

class EventData:
    def __init__(self, event):
        self.event_type = event['InvocationEventType']
        
        call_details = event['CallDetails'] 
        participants = call_details['Participants']

        self.hungup_leg = event.get('ActionData', {}).get('Parameters', {}).get('ParticipantTag', None)        
        self.wait_token = call_details.get('TransactionAttributes', {}).get('WaitToken', None)
        self.queue_url = call_details.get('TransactionAttributes', {}).get('QueueUrl', None)
        self.call_flow_instance_name = "call_flow_{}".format(call_details['TransactionId'])

        self.total_participants = len(participants)
        
        #to simplify step function code lets determine who is the main participant in the call => main_participant: for one LEG that is the main, if two legs then choose a Connected LEG-A otherwise LEG-B otherwise LEG-A 
        if self.total_participants == 1:
            main_participant = participants[0]
        elif self.total_participants == 2:
            leg_a = participants[0] if (participants[0]['ParticipantTag'] == 'LEG-A') else participants[1]
            leg_b = participants[0] if (participants[0]['ParticipantTag'] == 'LEG-B') else participants[1]

            main_participant = leg_a if (leg_a['Status'] == 'Connected') else leg_b
        else:
            raise Exception("Unexpected total_participants: {}".format(self.total_participants))

        self.main_participant_direction = main_participant['Direction']
        self.main_participant_to = main_participant['To']
        self.main_participant_from = main_participant['From']
        self.main_participant_status = main_participant.get('Status', 'Connected') #assume 'Connected' when no status sent
        
    def to_json(self):        
        return json.dumps(self.__dict__)

# Set LogLevel using environment variable, fallback to INFO if not present
logger = logging.getLogger()
try:
    log_level = os.environ["LogLevel"]
    if log_level not in ["INFO", "DEBUG"]:
        log_level = "INFO"
except:
    log_level = "INFO"
logger.setLevel(log_level)

stepfunctions = boto3.client("stepfunctions")
sqs = boto3.client('sqs')

def lambda_handler(event, context):
    try:   
        logger.info("Lambda called with event: {}".format(json.dumps(event)))

        #compute event_data
        event_data = EventData(event)
        #logger.info("Event Data: {}".format(event_data.to_json()))

        #find stepfunction arn call flow by did and throw if did is not found
        event_data.call_flow_arn = find_call_flow_arn_by_did(event_data)
  
        #process all 11 events as described by documentation: https://docs.aws.amazon.com/chime-sdk/latest/dg/pstn-invocations.html

        #initialize queue and stepfuntion for initial events for inbound and outbound respectively
        if event_data.event_type in ['NEW_INBOUND_CALL', 'NEW_OUTBOUND_CALL']:
            logger.info("First call event => creating queue and workflow")   
            #create the sqs queue that will handle this call actions        
            event_data.queue_url = create_actions_queue(event_data)            
            #start and execute new step function instance for this did
            start_execute_step_function(event_data, event)
            #wait until new message is available on queue, throws if no messages returned
            return wait_for_next_action(event_data)

        #This looks to happend for hangups just right after succesful aciton completion, it seems to always be followed by hangup action, so it could be ignored
        if event_data.event_type == 'ACTION_SUCCESSFUL' and event_data.main_participant_status == 'Disconnected': 
            logger.info("Returning empty actions for ACTION_SUCCESSFUL-Disconnected")
            return no_action_result()

        #procesing this informative event right here to simplify workflow design
        if event_data.event_type in ['ACTION_INTERRUPTED', 'RINGING']: 
            logger.info("Returning empty actions for: {}".format(event_data.event_type))  
            return no_action_result()

        #process success events as stepfuntion task success
        if event_data.event_type in ['ACTION_SUCCESSFUL', 'CALL_ANSWERED', 'CALL_UPDATE_REQUESTED', 'DIGITS_RECEIVED']:
            logger.info("Calling stepfunctions.send_task_success: {}".format(event_data.event_type))
            stepfunctions.send_task_success(taskToken=event_data.wait_token, output=json.dumps(event)) 
            #wait until new message is available on queue, throws if no messages returned
            return wait_for_next_action(event_data) 

        #treat failure events as errors to simplify workflow design 
        if event_data.event_type in ['INVALID_LAMBDA_RESPONSE', 'ACTION_FAILED']:                                
            logger.info("Calling stepfunctions.send_task_failure for: {}".format(event_data.event_type))  
            event_cause = event.get('ActionData', {}).get('ErrorMessage', 'No cause reported')
            stepfunctions.send_task_failure(taskToken=event_data.wait_token, error=event_data.event_type, cause=event_cause)
            #wait until new message is available on queue, throws if no messages returned
            return wait_for_next_action(event_data)

        if event_data.event_type == 'HANGUP':
            if event_data.hungup_leg == 'LEG-A':
                #treat hangup on LEG-A as error
                logger.info("Calling stepfunctions.send_task_failure for: HANGUP-LEG-A")            
                stepfunctions.send_task_failure(taskToken=event_data.wait_token, error=event_data.event_type, cause="Call Ended")  
            else:
                #treat hangup on LEG-B as positive path
                logger.info("Calling stepfunctions.send_task_success for: HANGUP-LEG-B")
                stepfunctions.send_task_success(taskToken=event_data.wait_token, output=json.dumps(event)) 
              
            if event_data.total_participants == 1 and event_data.main_participant_status == 'Disconnected':  
                #delete queue for final even                                 
                logger.info("Deleting queue: HANGUP-OneLEG-Disconnected")            
                sqs.delete_queue(QueueUrl=event_data.queue_url)
                return no_action_result()
            else:
                #wait until new message is available on queue
                return wait_for_next_action(event_data)
 
    except Exception as e:
        logger.error("Exception: {}".format(str(e)))

#auxiliary funtions

def no_action_result():
    return {"SchemaVersion": "1.0", "Actions": []};

def find_call_flow_arn_by_did(event_data):

    did =  event_data.main_participant_to if (event_data.main_participant_direction == 'Inbound') else event_data.main_participant_from

    call_flows_did_map = json.loads(os.environ['CallFlowsDIDMap'])

    return next((call_flow['ARN'] for call_flow in call_flows_did_map if call_flow['DID'] == did), None)
    
    raise Exception("No call flow found for number: {}".format(did))

def create_actions_queue(event_data):
    response = sqs.create_queue(
                QueueName=event_data.call_flow_instance_name,
                Attributes={'ReceiveMessageWaitTimeSeconds': '18'}
            )
    queue_url = response['QueueUrl']
    logger.info("Queue created: {}".format(queue_url))

    return queue_url

def start_execute_step_function(event_data, event):
    stepfunctions.start_execution(
        name=event_data.call_flow_instance_name,
        stateMachineArn=event_data.call_flow_arn,
        input=json.dumps({ "QueueUrl": event_data.queue_url, "Event": event })
    )
    logger.info("Step funtion executed")

def wait_for_next_action(event_data):
    logger.info("Reading message...")
    
    response = sqs.receive_message(
        QueueUrl=event_data.queue_url,
        MaxNumberOfMessages=1, 
        VisibilityTimeout=20,
        MessageAttributeNames=['All']
    )        
    message = response['Messages'][0]
    receipt_handle = message['ReceiptHandle']
    sqs.delete_message(
        QueueUrl=event_data.queue_url,
        ReceiptHandle=receipt_handle
    ) 
    #set result to message body with contains the action
    result = json.loads(message['Body'])
    
    logger.info("Message processed, returned Actions: {}".format(result))

    return result