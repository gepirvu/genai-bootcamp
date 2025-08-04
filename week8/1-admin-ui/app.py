#!/usr/bin/env python3
import os

import aws_cdk as cdk

from kb.stack import KnowledgeBase
from twin.stack import Twin

env=cdk.Environment(account=os.getenv('CDK_DEFAULT_ACCOUNT'), region='us-west-2')
app = cdk.App()
kb = KnowledgeBase(app, "KnowledgeBaseStack", env=env)
_ = Twin(app, "Twin",
         kb_arn=kb.kb.knowledge_base_arn,
         kb_id=kb.kb.knowledge_base_id,
         kb_data_src_id=kb.kb.data_source_id,
         kb_input_bucket=kb.input_bucket,
         custom_certificate_arn="arn:aws:acm:us-east-1:950363886497:certificate/83f17796-48de-4a8f-b027-6bd25e2ac957",
         custom_domain_name="twin.tech-george.com",
         env=env,
        )

app.synth()
