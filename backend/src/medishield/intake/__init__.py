"""Document intake channels besides the upload form: email (``POST /intake/email`` and SES inbound mail).

``email``    raw RFC 5322 message -> sender, Message-ID, subject and the document attachments
``service``  sender allow-list, SES verdicts, case creation through the normal upload validation, audit events
``ses``      the AWS Lambda handler behind the SES receipt rule (raw message in S3, verdicts in the event)
"""
