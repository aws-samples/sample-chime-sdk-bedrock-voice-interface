# Building a voice interface for generative AI assistants

This solution demonstrates how to create a voice interface for your existing Amazon Bedrock generative AI assistant, enabling customers to engage in phone-based conversations with your AI implementation. In a previous [blog](https://aws.amazon.com/blogs/messaging-and-targeting/visually-build-telephony-applications-with-aws-step-functions/), we demonstrated how combining AWS Step Functions and Amazon Chime SDK PSTN (Public Switched Telephone Network) audio service streamlines the development of reliable telephony applications through visual workflow design.

## Solution Overview

The solution provides two main components:

- **Event Router**: A Lambda function that routes JSON messages between Step Functions and PSTN audio service
- **Demo Workflow**: A Step Function workflow implementing the sample telephony application

## Sample telephony application

This application builds a voice communication interface that connects with the Amazon Nova Micro model in Amazon Bedrock (Figure 1) as described in this [blog](https://aws.amazon.com/blogs/messaging-and-targeting/building-voice-interface-for-genai-assistant/). 

![Demo-Workflow](/images/conversational-genai-agent.png)

Figure 1 – Step Functions workflow build with Workflow Studio to enables voice communication to a Generative AI assistant.

## Walkthrough

1. Inbound call arrives
2. System plays welcome message
3. System asks caller for questions
4. Voice recording starts, stopping when silence is detected
5. Parallel flows begin:
   - First flow:
     1. Plays some music while the caller is on-hold
   - Second flow:
     1. Transcribes the recording using Amazon Transcribe
     2. Sends transcribed question to the Amazon Nova Micro model in Amazon Bedrock
     3. Upon receiving the response, stops the on-hold music
6. Text-to-speech plays the model's answer
7. System asks for additional questions and loops to Step 4 or ends the call

## Prerequisites

1. AWS Management Console access
2. Node.js and npm installed
3. AWS CLI installed and configured
4. [Enable access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-modify.html) to the Amazon Nova Micro model through the Amazon Bedrock console

## Getting Started

1. **Clone the repository**
   ```bash
   git clone https://github.com/aws-samples/sample-chime-sdk-bedrock-voice-interface

   cd sample-chime-sdk-bedrock-voice-interface
   
   npm install
   ```
2. **Bootstrap the stack**
   ```bash
   #default AWS CLI credentials are used, otherwise use the –-profile parameter
   #provide the <account-id> and <region> to deploy this stack
   cdk bootstrap aws://<account-id>/<region>
   ```

3. **Deploy the stack**
   ```bash
   #default AWS CLI credentials are used, otherwise use the –-profile parameter
   #phoneAreaCode: the United States area code used to provision the phone number
   cdk deploy –-context phoneAreaCode=NPA
   ```

## Deployed Resources

The CDK stack creates:

- `phoneNumberBedrock` – Provisioned phone number for the demo application
- `sipMediaApp` – SIP media application that routes calls to `lambdaProcessPSTNAudioServiceCalls` 
- `sipRule` – SIP rule that directs calls from `phoneNumberBedrock` to `sipMediaApp`
- `lambdaProcessPSTNAudioServiceCalls` – Lambda function for call processing 
- `roleLambdaProcessPSTNAudioServiceCalls` – IAM Role for `lambdaProcessPSTNAudioServiceCalls`
- `stepfunctionBedrockWorkflow` – Step Functions workflow for the telephony application
- `roleStepfuntionBedrockWorkflow` – IAM Role for `stepfunctionBedrockWorkflow`
- `s3BucketApp` – S3 bucket for storing customer questions recordings
- `s3BucketPolicy` – IAM Policy granting PSTN audio service access to s3BucketApp
- `lambdaAudioTranscription` – Lambda function for audio transcription
- `lambdaLayerForTranscription` – Lambda layer required for `lambdaAudioTranscription`
- `roleLambdaAudioTranscription` – IAM Role for `lambdaAudioTranscription`

Once deployed, call the provisioned phone number to test the sample application. 

## Cleanup

**To clean up this demo, execute:**
   ```bash
   cdk destroy
   ```

## Security

- Lambda functions run with least-privilege permissions
- All resources use AWS IAM for access control
- Communication between services occurs through secure AWS channels

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

This project is licensed under the MIT-0 License.


