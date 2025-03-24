#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { AmazonChimeSdkBedrockVoiceInterfaceStack } from '../lib/amazon-chime-sdk-bedrock-voice-interface-stack';
//import { AwsSolutionsChecks } from 'cdk-nag'
//import { Aspects } from 'aws-cdk-lib';

const app = new cdk.App();

//Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }))

new AmazonChimeSdkBedrockVoiceInterfaceStack(app, 'AmazonChimeSdkBedrockVoiceInterface0Stack', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION }
});