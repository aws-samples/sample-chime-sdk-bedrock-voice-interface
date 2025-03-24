import * as fs from 'fs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as chime from "cdk-amazon-chime-resources";
import { Fn } from 'aws-cdk-lib';
import { Duration } from "aws-cdk-lib/core";
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';

export class AmazonChimeSdkBedrockVoiceInterfaceStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const phoneAreaCode: number = this.node.tryGetContext('phoneAreaCode') as number;

    const chimePhoneNumber = new chime.ChimePhoneNumber(this, 'phoneNumberBedrock', {
      phoneAreaCode: Number(phoneAreaCode),
      phoneNumberType: chime.PhoneNumberType.LOCAL,
      phoneProductType: chime.PhoneProductType.SMA,
    });

    const phoneNumberPart = Fn.select(1, Fn.split('+', chimePhoneNumber.phoneNumber));
    const bucketUniqueId = Fn.sub('pstn-media-apps-${phoneNumber}', {
      phoneNumber: phoneNumberPart
    });
    const s3BucketApp  = new s3.Bucket(this, 's3BucketApp', {
      bucketName: bucketUniqueId,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,          
    });
    s3BucketApp.addToResourcePolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject','s3:PutObject','s3:PutObjectAcl'],
      resources: [s3BucketApp.arnForObjects('*')],
      principals: [new iam.ServicePrincipal('voiceconnector.chime.amazonaws.com')]
    }));

    new s3deploy.BucketDeployment(this, 's3BucketFileUpload', {
      sources: [s3deploy.Source.asset(path.join(__dirname, '../files'))],  
      destinationBucket: s3BucketApp,
      contentType: 'audio/wav'
    });

    s3BucketApp.node.addDependency(chimePhoneNumber);

    const roleLambdaAudioTranscription  = new iam.Role(this, "roleLambdaAudioTranscription", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      inlinePolicies: {
        ["lambdaPolicy"]: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              resources: ["*"],
              actions: [
                "transcribe:StartStreamTranscription"                
              ]
            }),
            new iam.PolicyStatement({
              resources: [s3BucketApp.arnForObjects('*')],
              actions: [
                "s3:GetObject",
                "s3:ListBucket"              
              ]
            })
          ],
        }),
      },
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaBasicExecutionRole"
        ),
      ],
    });

    const lambdaLayerForTranscription = new lambda.LayerVersion(this, 'lambdaLayerForTranscription', {
      code: lambda.Code.fromAsset('src/layer_for_transcription/transcribe.zip'),
      compatibleRuntimes: [
        lambda.Runtime.PYTHON_3_13
      ],
      compatibleArchitectures: [
        lambda.Architecture.ARM_64,
        lambda.Architecture.X86_64
      ]
    });

    const lambdaAudioTranscription = new lambda.Function(this, "lambdaAudioTranscription", {
      functionName: "transcribe-realtime-audio-from-s3",
      runtime: lambda.Runtime.PYTHON_3_13, 
      handler: "lambda_function.lambda_handler",
      code: lambda.Code.fromAsset('src/lambda_ transcribe_realtime_audio_from_s3'),
      role: roleLambdaAudioTranscription,
      memorySize: 4096,
      timeout: Duration.seconds(60)
    });

    lambdaAudioTranscription.addLayers(lambdaLayerForTranscription);

    const NOVA_MICRO_MODEL_ID = "amazon.nova-micro-v1:0";
    const novaMicroArn = `arn:aws:bedrock:${cdk.Stack.of(this).region}::foundation-model/${NOVA_MICRO_MODEL_ID}`;

    const roleStepfuntionBedrockWorkflow = new iam.Role(this, "roleStepfuntionBedrockWorkflow", {
      assumedBy: new iam.ServicePrincipal("states.amazonaws.com"),
      inlinePolicies: {
        ["wokflowPolicy"]: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              resources: ["*"],
              actions: [
                "sqs:SendMessage",
                "chime:UpdateSipMediaApplicationCall"
              ],              
            }),
            new iam.PolicyStatement({
              resources: [novaMicroArn],
              actions: [
                "bedrock:InvokeModel",
              ],              
            }),
            new iam.PolicyStatement({
              resources: [lambdaAudioTranscription.functionArn],
              actions: [
                "lambda:InvokeFunction",
              ],              
            })
          ],
        }),
      }
    });

    const workflowFilePath = path.join(__dirname, '../src/stepfunction_conversational_genai_agent_english/definition.asl.json');
    let workflowString = fs.readFileSync(workflowFilePath, 'utf8');
    const workflowJSON = JSON.parse(workflowString);
    workflowJSON.States.Init.Assign.Environment.BuckectName = s3BucketApp.bucketName;
    workflowJSON.States.Parallel.Branches[1].States["Transcribe Question"].Parameters.FunctionName = lambdaAudioTranscription.functionArn;
    workflowString = JSON.stringify(workflowJSON, null, 2);    
    
    const stepfunctionBedrockWorkflow = new sfn.StateMachine(this, 'stepfunctionBedrockWorkflow', {
      definitionBody: sfn.DefinitionBody.fromString(workflowString),
      stateMachineName: 'conversational-genai-agent-english',
      role: roleStepfuntionBedrockWorkflow
    });

    const roleLambdaProcessPSTNAudioServiceCalls = new iam.Role(this, "roleLambdaProcessPSTNAudioServiceCalls", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      inlinePolicies: {
        ["lambdaPolicy"]: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              resources: ["*"],
              actions: [
                "states:StartExecution",
                "states:SendTaskFailure",
                "states:SendTaskSuccess",
                "sqs:GetQueueUrl",
                "sqs:ReceiveMessage",
                "sqs:CreateQueue",
                "sqs:DeleteMessage",
                "sqs:DeleteQueue"
              ],
            }),
          ],
        }),
      },
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaBasicExecutionRole"
        ),
      ],
    });

    const lambdaProcessPSTNAudioServiceCalls = new lambda.Function(this, "lambdaProcessPSTNAudioServiceCalls", {
      runtime: lambda.Runtime.PYTHON_3_13, 
      handler: "lambda_function.lambda_handler",
      code: lambda.Code.fromAsset('src/lambda_process_pstn_audio_service_calls'),
      environment: {
        CallFlowsDIDMap: `[{"DID":"${chimePhoneNumber.phoneNumber}","ARN":"${stepfunctionBedrockWorkflow.stateMachineArn}"}]`
      },
      timeout: Duration.seconds(25),
      role: roleLambdaProcessPSTNAudioServiceCalls,
    });
    
    const sipMediaApp = new chime.ChimeSipMediaApp(this, 'sipMediaApp', {
      name: "VisualMediaApp",
      region: this.region,
      endpoint: lambdaProcessPSTNAudioServiceCalls.functionArn
    });

    const sipRule = new chime.ChimeSipRule(this, 'sipRule', {
      name: "VisualSipRule",
      triggerType: chime.TriggerType.TO_PHONE_NUMBER,
      triggerValue: chimePhoneNumber.phoneNumber,
      targetApplications: [
        {
          region: this.region,
          priority: 1,
          sipMediaApplicationId: sipMediaApp.sipMediaAppId,
        },
      ],
    });

  }
}
