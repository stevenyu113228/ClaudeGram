"""CDK Stack for Telegram Bot with Claude Agent SDK."""
from pathlib import Path

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Size,
    Stack,
    aws_apigateway as apigw,
    aws_ecr_assets as ecr_assets,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    CfnOutput,
)
from constructs import Construct

# Path to source code and dependencies
SRC_DIR = Path(__file__).parent.parent.parent / "src"
LAYER_DIR = Path(__file__).parent.parent.parent / ".lambda-layer"


class TelegramBotStack(Stack):
    """CDK Stack for Telegram Chatbot with Claude Agent SDK."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # =============================================================
        # S3 Bucket for SQLite Database
        # =============================================================
        database_bucket = s3.Bucket(
            self,
            "DatabaseBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # =============================================================
        # Environment Variables (from CDK context or defaults)
        # =============================================================
        telegram_bot_token = self.node.try_get_context("telegram_bot_token") or ""
        webhook_secret = self.node.try_get_context("webhook_secret") or ""
        anthropic_api_key = self.node.try_get_context("anthropic_api_key") or ""
        anthropic_base_url = self.node.try_get_context("anthropic_base_url") or ""
        anthropic_model = (
            self.node.try_get_context("anthropic_model") or "claude-sonnet-4-20250514"
        )
        admin_password = self.node.try_get_context("admin_password") or ""

        common_env = {
            "DATABASE_BUCKET": database_bucket.bucket_name,
            "DATABASE_KEY": "chatbot.db",
            "ANTHROPIC_API_KEY": anthropic_api_key,
            "ANTHROPIC_MODEL": anthropic_model,
        }

        if anthropic_base_url:
            common_env["ANTHROPIC_BASE_URL"] = anthropic_base_url

        # =============================================================
        # Lambda Layer for Dependencies
        # =============================================================
        deps_layer = lambda_.LayerVersion(
            self,
            "DependenciesLayer",
            code=lambda_.Code.from_asset(str(LAYER_DIR)),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_11],
            description="Python dependencies for Telegram Bot",
        )

        # =============================================================
        # Summarizer Lambda (Docker Container with Playwright)
        # =============================================================
        # Project root for Docker build context
        PROJECT_ROOT = Path(__file__).parent.parent.parent

        summarizer_handler = lambda_.DockerImageFunction(
            self,
            "SummarizerHandler",
            code=lambda_.DockerImageCode.from_image_asset(
                str(PROJECT_ROOT),
                file="src/summarizer_handler/Dockerfile",
                platform=ecr_assets.Platform.LINUX_AMD64,  # ARM Mac 需要指定平台
            ),
            architecture=lambda_.Architecture.X86_64,  # Lambda 使用 x86_64
            timeout=Duration.minutes(5),
            memory_size=2048,
            ephemeral_storage_size=Size.mebibytes(2048),
            environment={
                "ANTHROPIC_API_KEY": anthropic_api_key,
                "ANTHROPIC_MODEL": anthropic_model,
                **({"ANTHROPIC_BASE_URL": anthropic_base_url} if anthropic_base_url else {}),
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
            description="URL summarization with Playwright for JS rendering",
        )

        # =============================================================
        # Telegram Handler Lambda
        # =============================================================
        telegram_handler = lambda_.Function(
            self,
            "TelegramHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="telegram_handler.handler.lambda_handler",
            code=lambda_.Code.from_asset(
                str(SRC_DIR),
                exclude=[
                    "**/__pycache__",
                    "**/*.pyc",
                    "summarizer_handler/*",
                ],
            ),
            layers=[deps_layer],
            timeout=Duration.seconds(120),
            memory_size=1536,
            ephemeral_storage_size=Size.mebibytes(1024),
            environment={
                **common_env,
                "TELEGRAM_BOT_TOKEN": telegram_bot_token,
                "WEBHOOK_SECRET": webhook_secret,
                "SUMMARIZER_FUNCTION_NAME": summarizer_handler.function_name,
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
            description="Main Telegram webhook handler with file support",
        )

        # =============================================================
        # Admin Handler Lambda
        # =============================================================
        admin_handler = lambda_.Function(
            self,
            "AdminHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="admin_handler.handler.lambda_handler",
            code=lambda_.Code.from_asset(
                str(SRC_DIR),
                exclude=[
                    "**/__pycache__",
                    "**/*.pyc",
                    "summarizer_handler/*",
                ],
            ),
            layers=[deps_layer],
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                **common_env,
                "ADMIN_PASSWORD": admin_password,
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
            description="Admin panel handler",
        )

        # =============================================================
        # Permissions
        # =============================================================
        database_bucket.grant_read_write(telegram_handler)
        database_bucket.grant_read_write(admin_handler)

        # Allow TelegramHandler to invoke Summarizer
        summarizer_handler.grant_invoke(telegram_handler)

        # =============================================================
        # API Gateway
        # =============================================================
        api = apigw.RestApi(
            self,
            "BotApi",
            rest_api_name="Telegram Bot API",
            description="API for Telegram Bot with Claude Agent SDK",
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                # Disable API Gateway logging to avoid CloudWatch role requirement
                logging_level=apigw.MethodLoggingLevel.OFF,
                throttling_rate_limit=100,
                throttling_burst_limit=200,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_credentials=True,
            ),
        )

        # Webhook endpoint
        webhook_resource = api.root.add_resource("webhook")
        webhook_resource.add_method(
            "POST",
            apigw.LambdaIntegration(telegram_handler),
        )

        # Admin endpoints
        admin_resource = api.root.add_resource("admin")

        # Admin root (dashboard)
        admin_resource.add_method(
            "GET",
            apigw.LambdaIntegration(admin_handler),
        )

        # Admin login
        admin_login = admin_resource.add_resource("login")
        admin_login.add_method("GET", apigw.LambdaIntegration(admin_handler))
        admin_login.add_method("POST", apigw.LambdaIntegration(admin_handler))

        # Admin logout
        admin_logout = admin_resource.add_resource("logout")
        admin_logout.add_method("POST", apigw.LambdaIntegration(admin_handler))

        # Admin users
        admin_users = admin_resource.add_resource("users")
        admin_users.add_method("GET", apigw.LambdaIntegration(admin_handler))
        admin_users.add_method("POST", apigw.LambdaIntegration(admin_handler))

        admin_user = admin_users.add_resource("{user_id}")
        admin_user.add_method("DELETE", apigw.LambdaIntegration(admin_handler))

        # Admin groups
        admin_groups = admin_resource.add_resource("groups")
        admin_groups.add_method("GET", apigw.LambdaIntegration(admin_handler))
        admin_groups.add_method("POST", apigw.LambdaIntegration(admin_handler))

        admin_group = admin_groups.add_resource("{group_id}")
        admin_group.add_method("DELETE", apigw.LambdaIntegration(admin_handler))

        # Admin logs
        admin_logs = admin_resource.add_resource("logs")
        admin_logs.add_method("GET", apigw.LambdaIntegration(admin_handler))

        # =============================================================
        # Outputs
        # =============================================================
        CfnOutput(
            self,
            "ApiUrl",
            value=api.url,
            description="API Gateway URL",
        )

        CfnOutput(
            self,
            "WebhookUrl",
            value=f"{api.url}webhook",
            description="Telegram Webhook URL",
        )

        CfnOutput(
            self,
            "AdminUrl",
            value=f"{api.url}admin",
            description="Admin Panel URL",
        )

        CfnOutput(
            self,
            "DatabaseBucketName",
            value=database_bucket.bucket_name,
            description="S3 Bucket for database",
        )
