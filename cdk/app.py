#!/usr/bin/env python3
"""AWS CDK App entry point for Telegram Bot infrastructure."""
import os

import aws_cdk as cdk

from stacks.bot_stack import TelegramBotStack

app = cdk.App()

# Get environment configuration
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "ap-northeast-1"),
)

TelegramBotStack(
    app,
    "TelegramBotStack",
    env=env,
    description="Telegram Chatbot with Claude Agent SDK",
)

app.synth()
