"""
REdI Email Processing API Server
===================================

Main Flask application for processing REdI inbox emails.
Handles pre-filtering, GPT analysis, sensitivity detection,
and response generation.

Author: Sean Wing
Date: 2026-01-02
Version: 2.0
"""

import os
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from flask import Flask, request, jsonify
from functools import wraps
import traceback

# Import database module
from database import init_database_pool, EmailDatabase

# Configure comprehensive logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/redi/email_processor.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Initialize database pool (global)
db_pool = init_database_pool()
email_db = EmailDatabase(db_pool)

# Initialize Flask app
app = Flask(__name__)

# Load configuration from environment
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o')
OPENAI_TEMPERATURE = float(os.getenv('OPENAI_TEMPERATURE', '0'))
OPENAI_MAX_TOKENS = int(os.getenv('OPENAI_MAX_TOKENS', '1000'))

CONFIDENCE_THRESHOLD_HIGH = float(os.getenv('CONFIDENCE_THRESHOLD_HIGH', '0.8'))
CONFIDENCE_THRESHOLD_MODERATE = float(os.getenv('CONFIDENCE_THRESHOLD_MODERATE', '0.5'))
CONFIDENCE_THRESHOLD_LOW = float(os.getenv('CONFIDENCE_THRESHOLD_LOW', '0.3'))

API_KEY = os.getenv('REDI_API_KEY', 'your-secure-api-key-here')


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class EmailContext:
    """Context data about the user (bookings, certificates)"""
    user_bookings: List[Dict[str, Any]]
    user_certificates: List[Dict[str, Any]]


@dataclass
class FilterResult:
    """Result of pre-filtering check"""
    skip_gpt: bool
    reason: str
    confidence: float
    category: str


@dataclass
class SensitivityResult:
    """Result of sensitivity detection"""
    flags: List[str]
    max_confidence: float
    should_block: bool
    reasoning: str


@dataclass
class GPTResponse:
    """Structured response from GPT"""
    is_new_email: bool
    sender_first_name: str
    enquiry_type: str
    recommended_response: str
    confidence: float
    action: str


@dataclass
class ProcessingDecision:
    """Final decision about how to handle email"""
    should_respond: bool
    confidence: float
    category: str
    action: str
    reasoning_chain: List[str]
    sensitivity_flags: List[str]


@dataclass
class APIResponse:
    """Complete API response structure"""
    success: bool
    processing_time: float
    decision: ProcessingDecision
    response: Optional[Dict[str, Any]]
    actions: List[Dict[str, Any]]
    human_review: Dict[str, Any]
    metadata: Dict[str, Any]
    error: Optional[Dict[str, Any]] = None


# ============================================================================
# AUTHENTICATION
# ============================================================================

def require_api_key(f):
    """
    Decorator to require API key authentication.
    
    Args:
        f: Function to decorate
        
    Returns:
        Decorated function that checks for valid API key
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            logger.warning("Request missing Bearer token")
            return jsonify({
                'success': False,
                'error': {
                    'code': 'MISSING_AUTH',
                    'message': 'Authorization header required'
                }
            }), 401
        
        api_key = auth_header.replace('Bearer ', '')
        
        if api_key != API_KEY:
            logger.warning(f"Invalid API key attempted: {api_key[:10]}...")
            return jsonify({
                'success': False,
                'error': {
                    'code': 'INVALID_AUTH',
                    'message': 'Invalid API key'
                }
            }), 401
        
        return f(*args, **kwargs)
    
    return decorated


# ============================================================================
# PRE-FILTERING MODULE
# ============================================================================

class PreFilter:
    """
    Pre-filtering logic to skip GPT for obvious cases.
    
    Handles:
    - Out of office replies
    - System notifications
    - Spam/marketing
    - Delivery failures
    """
    
    @staticmethod
    def should_skip_gpt(email: Dict[str, Any]) -> FilterResult:
        """
        Determine if email should skip GPT processing.
        
        Args:
            email: Email data dictionary
            
        Returns:
            FilterResult with skip decision and metadata
        """
        logger.info(f"Pre-filtering email: {email.get('subject', 'No subject')}")
        
        subject = email.get('subject', '').lower()
        body = email.get('bodyText', '').lower()
        from_email = email.get('from', {}).get('email', '').lower()
        
        # Check for out of office
        if any(phrase in subject for phrase in [
            'out of office',
            'automatic reply',
            'autoreply',
            'out of the office'
        ]):
            logger.info("Filtered: Out of office reply detected")
            return FilterResult(
                skip_gpt=True,
                reason='out_of_office',
                confidence=0.15,
                category='system_generated'
            )
        
        # Check for system notifications
        if any(sender in from_email for sender in [
            'noreply@',
            'donotreply@',
            'no-reply@',
            'mailer-daemon'
        ]):
            logger.info(f"Filtered: System notification from {from_email}")
            return FilterResult(
                skip_gpt=True,
                reason='system_notification',
                confidence=0.15,
                category='system_generated'
            )
        
        # Check for delivery failures
        if any(phrase in subject for phrase in [
            'undeliverable',
            'delivery status notification',
            'returned mail',
            'mail delivery failed'
        ]):
            logger.info("Filtered: Delivery failure notification")
            return FilterResult(
                skip_gpt=True,
                reason='delivery_failure',
                confidence=0.1,
                category='system_generated'
            )
        
        # Check for spam/marketing
        if any(phrase in body for phrase in [
            'unsubscribe',
            'click here to buy',
            'limited time offer',
            'act now'
        ]) or any(sender in from_email for sender in [
            'marketing@',
            'newsletter@',
            'promo@'
        ]):
            logger.info("Filtered: Spam/marketing detected")
            return FilterResult(
                skip_gpt=True,
                reason='spam_marketing',
                confidence=0.1,
                category='spam'
            )
        
        # Check for ongoing threads
        if any(subject.startswith(prefix) for prefix in ['re:', 'fwd:', 'fw:']):
            logger.info("Detected ongoing thread - will lower confidence")
            return FilterResult(
                skip_gpt=False,
                reason='ongoing_thread',
                confidence=0.25,  # Lower confidence but still process
                category='thread'
            )
        
        # No filter matched - proceed to GPT
        logger.info("No pre-filter matched - proceeding to GPT")
        return FilterResult(
            skip_gpt=False,
            reason='none',
            confidence=0.5,
            category='unknown'
        )


# ============================================================================
# SENSITIVITY DETECTION MODULE
# ============================================================================

class SensitivityDetector:
    """
    Detect sensitive email content that should not receive AI responses.
    
    Categories:
    - Complaints
    - Clinical urgency
    - Financial disputes
    - Escalation language
    - HR/workplace issues
    - Personal crises
    """
    
    # Sensitivity keyword mappings
    SENSITIVITY_PATTERNS = {
        'complaint': {
            'keywords': ['complaint', 'unhappy', 'disappointed', 'unacceptable', 
                        'poor', 'terrible', 'inadequate', 'frustrated', 'angry'],
            'max_confidence': 0.1,
            'block': True
        },
        'clinical_urgent': {
            'keywords': ['urgent', 'emergency', 'asap', 'immediately', 'critical',
                        'code blue', 'cardiac arrest', 'patient emergency'],
            'max_confidence': 0.15,
            'block': False  # Still respond but with phone number
        },
        'financial': {
            'keywords': ['refund', 'payment issue', 'billing error', 'charged incorrectly',
                        'invoice problem', 'charged twice', 'incorrect charge'],
            'max_confidence': 0.2,
            'block': True
        },
        'escalation': {
            'keywords': ['speak to manager', 'supervisor', 'escalate', 'legal action',
                        'solicitor', 'ombudsman', 'formal complaint', 'take this further'],
            'max_confidence': 0.1,
            'block': True
        },
        'hr_sensitive': {
            'keywords': ['harassment', 'discrimination', 'bullying', 'incident report',
                        'unsafe workplace', 'concern about staff', 'inappropriate behavior'],
            'max_confidence': 0.05,
            'block': True
        },
        'personal_crisis': {
            'keywords': ['deceased', 'bereavement', 'death in family', 'funeral',
                        'serious illness', 'medical emergency', 'family crisis'],
            'max_confidence': 0.2,
            'block': True
        }
    }
    
    @staticmethod
    def detect(email: Dict[str, Any]) -> SensitivityResult:
        """
        Detect sensitivity issues in email content.
        
        Args:
            email: Email data dictionary
            
        Returns:
            SensitivityResult with detected flags and constraints
        """
        logger.info("Running sensitivity detection...")
        
        subject = email.get('subject', '').lower()
        body = email.get('bodyText', '').lower()
        combined_text = f"{subject} {body}"
        
        detected_flags = []
        min_confidence = 1.0  # Start at max, reduce as we find issues
        should_block = False
        reasoning_parts = []
        
        # Check each sensitivity category
        for category, config in SensitivityDetector.SENSITIVITY_PATTERNS.items():
            keywords = config['keywords']
            max_conf = config['max_confidence']
            block = config['block']
            
            # Check if any keywords match
            matches = [kw for kw in keywords if kw in combined_text]
            
            if matches:
                detected_flags.append(category)
                min_confidence = min(min_confidence, max_conf)
                if block:
                    should_block = True
                
                reasoning_parts.append(
                    f"Detected {category}: {', '.join(matches[:3])}"
                )
                
                logger.warning(
                    f"SENSITIVITY ALERT: {category} detected - "
                    f"matches: {matches[:3]}"
                )
        
        # Build reasoning string
        if detected_flags:
            reasoning = "; ".join(reasoning_parts)
        else:
            reasoning = "No sensitivity issues detected"
            logger.info("No sensitivity flags detected")
        
        return SensitivityResult(
            flags=detected_flags,
            max_confidence=min_confidence,
            should_block=should_block,
            reasoning=reasoning
        )


# ============================================================================
# GPT CLIENT MODULE
# ============================================================================

class GPTClient:
    """
    OpenAI GPT API client with retry logic and error handling.
    """
    
    def __init__(self, api_key: str, model: str, temperature: float, max_tokens: int):
        """
        Initialize GPT client.
        
        Args:
            api_key: OpenAI API key
            model: Model name (e.g., 'gpt-4o')
            temperature: Temperature setting (0-1)
            max_tokens: Maximum tokens in response
        """
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        logger.info(f"GPT Client initialized: {model}, temp={temperature}")
    
    def call_gpt(
        self,
        email: Dict[str, Any],
        context: EmailContext,
        system_prompt: str
    ) -> Optional[GPTResponse]:
        """
        Call GPT API with email and context.
        
        Args:
            email: Email data
            context: User context (bookings, certificates)
            system_prompt: System instructions for GPT
            
        Returns:
            GPTResponse object or None if error
        """
        try:
            import openai
            
            openai.api_key = self.api_key
            
            # Build user message with email and context
            user_message = self._build_user_message(email, context)
            
            logger.info(f"Calling GPT API: {self.model}")
            logger.debug(f"User message length: {len(user_message)} chars")
            
            # Call OpenAI API
            start_time = time.time()
            
            response = openai.ChatCompletion.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"}
            )
            
            api_time = time.time() - start_time
            
            # Extract response
            content = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            
            logger.info(
                f"GPT API call successful: {api_time:.2f}s, "
                f"{tokens_used} tokens"
            )
            
            # Parse JSON response
            result = json.loads(content)
            
            return GPTResponse(
                is_new_email=result.get('is_new_email', True),
                sender_first_name=result.get('sender_first_name', ''),
                enquiry_type=result.get('enquiry_type', 'general'),
                recommended_response=result.get('recommended_response', ''),
                confidence=result.get('confidence', 0.5),
                action=result.get('action', 'none')
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GPT JSON response: {e}")
            logger.error(f"Raw response: {content[:500]}")
            return None
            
        except Exception as e:
            logger.error(f"GPT API call failed: {e}")
            logger.error(traceback.format_exc())
            return None
    
    def _build_user_message(
        self,
        email: Dict[str, Any],
        context: EmailContext
    ) -> str:
        """
        Build user message with email content and context.
        
        Args:
            email: Email data
            context: User context
            
        Returns:
            Formatted user message string
        """
        message = f"""
Email Details:
--------------
From: {email.get('from', {}).get('name', '')} <{email.get('from', {}).get('email', '')}>
Subject: {email.get('subject', '')}
Received: {email.get('receivedDateTime', '')}

Body:
{email.get('bodyText', '')}

User Context:
-------------
Upcoming Bookings ({len(context.user_bookings)}):
{json.dumps(context.user_bookings, indent=2)}

Completed Certificates ({len(context.user_certificates)}):
{json.dumps(context.user_certificates, indent=2)}

Please analyze this email and provide your response in JSON format.
"""
        return message


# ============================================================================
# TEMPLATE ENGINE MODULE
# ============================================================================

class TemplateEngine:
    """
    Generate email responses from templates.
    """
    
    # Template library (in production, load from files)
    TEMPLATES = {
        'certificate_found': """
Hi {{firstName}},

Thank you for contacting REdI. I can confirm your certificate for {{courseName}} completed on {{courseDate}} is available.

Your certificate will be sent to you separately via email shortly. If you don't receive it within 24 hours, please let us know.

Kind regards,
REdI-AI (Automated Inbox Assistant)

---
This is an automated response. Our inbox is monitored and all emails are followed up by our education team. Responses may take up to 5 business days for complex enquiries.
""",
        
        'certificate_not_found': """
Hi {{firstName}},

Thank you for contacting REdI. I don't have a record of a completed course in our system, or your course may be marked as incomplete.

Our education team will review your enrolment records and follow up with you within 5 business days.

If your matter is urgent, please call our Duty Nurse Educator on (07) 3647 0106 during business hours.

Kind regards,
REdI-AI (Automated Inbox Assistant)

---
This is an automated response. Our inbox is monitored and all emails are followed up by our education team.
""",
        
        'cancellation_confirmed': """
Hi {{firstName}},

Thank you for contacting REdI. I can see you're booked for:
{{courseName}} on {{courseDate}} at {{courseTime}}, {{courseVenue}}

Your cancellation has been processed. You'll receive a confirmation email shortly.

If you'd like to rebook for a different date, please visit our booking system:
👉 https://tinyurl.com/bookREdIALS

Kind regards,
REdI-AI (Automated Inbox Assistant)

---
This is an automated response. Our inbox is monitored and all emails are followed up by our education team.
""",
        
        'course_availability': """
Hi {{firstName}},

Thank you for your interest in REdI courses. The easiest way to see all available dates and book your course is through our online booking system:

👉 https://tinyurl.com/bookREdIALS

This shows real-time availability for all our courses including ALS, BLS, NLS, APLS, and EPLS.

If you have specific requirements or need assistance with booking, our team will be happy to help within 5 business days.

Kind regards,
REdI-AI (Automated Inbox Assistant)

---
This is an automated response. Our inbox is monitored and all emails are followed up by our education team.
"""
    }
    
    @staticmethod
    def generate_response(
        template_id: str,
        variables: Dict[str, str]
    ) -> str:
        """
        Generate email response from template.
        
        Args:
            template_id: Template identifier
            variables: Variables to substitute
            
        Returns:
            Rendered email body
        """
        logger.info(f"Generating response from template: {template_id}")
        
        template = TemplateEngine.TEMPLATES.get(template_id, '')
        
        if not template:
            logger.warning(f"Template not found: {template_id}")
            return ""
        
        # Simple variable substitution
        response = template
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            response = response.replace(placeholder, str(value))
        
        logger.debug(f"Generated response length: {len(response)} chars")
        
        return response


# ============================================================================
# EMAIL PROCESSOR (Main Orchestrator)
# ============================================================================

class EmailProcessor:
    """
    Main orchestrator for email processing pipeline.
    
    Steps:
    1. Pre-filter
    2. Sensitivity detection
    3. GPT analysis (if not filtered)
    4. Confidence adjustment
    5. Decision making
    6. Response generation
    """
    
    def __init__(self):
        """Initialize email processor with all components."""
        self.pre_filter = PreFilter()
        self.sensitivity_detector = SensitivityDetector()
        self.gpt_client = GPTClient(
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL,
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS
        )
        self.template_engine = TemplateEngine()
        
        # Load system prompt (in production, load from file)
        self.system_prompt = self._load_system_prompt()
        
        logger.info("EmailProcessor initialized")
    
    def process(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process email and return decision.
        
        Args:
            request_data: Complete email request data
            
        Returns:
            API response dictionary
        """
        start_time = time.time()
        email_id = request_data.get('emailId', 'unknown')
        subject = request_data.get('subject', 'No subject')
        
        logger.info("="*60)
        logger.info(f"Processing email: {email_id}")
        logger.info(f"Subject: {subject}")
        logger.info("="*60)
        
        reasoning_chain = []
        record_id = None
        
        try:
            # Create database record
            record_id = email_db.create_email_record(
                email_data=request_data,
                context=request_data.get('context', {})
            )
            email_db.log_processing_step(
                record_id, 'INFO', 'start', 
                f'Processing email: {subject}'
            )
            
            # Step 1: Pre-filtering
            filter_result = self.pre_filter.should_skip_gpt(request_data)
            reasoning_chain.append(f"Pre-filter: {filter_result.reason}")
            email_db.log_processing_step(
                record_id, 'INFO', 'pre_filter',
                f'Pre-filter result: {filter_result.reason}',
                {'skip_gpt': filter_result.skip_gpt, 'confidence': filter_result.confidence}
            )
            
            if filter_result.skip_gpt:
                logger.info(f"Email filtered: {filter_result.reason}")
                
                # Update database with filter result
                decision_dict = {
                    'shouldRespond': False,
                    'confidence': filter_result.confidence,
                    'category': filter_result.category,
                    'action': 'none',
                    'sensitivityFlags': [],
                    'humanReview': {
                        'required': False,
                        'priority': 'low',
                        'reason': filter_result.reason
                    }
                }
                
                email_db.update_processing_result(
                    record_id,
                    decision_dict,
                    time.time() - start_time,
                    pre_filter_reason=filter_result.reason,
                    skipped_gpt=True
                )
                
                return self._build_filtered_response(
                    filter_result, 
                    reasoning_chain,
                    time.time() - start_time
                )
            
            # Step 2: Sensitivity detection
            sensitivity = self.sensitivity_detector.detect(request_data)
            reasoning_chain.append(f"Sensitivity: {sensitivity.reasoning}")
            email_db.log_processing_step(
                record_id, 'INFO' if not sensitivity.flags else 'WARNING',
                'sensitivity',
                sensitivity.reasoning,
                {'flags': sensitivity.flags, 'should_block': sensitivity.should_block}
            )
            
            # Step 3: Build context
            context = EmailContext(
                user_bookings=request_data.get('context', {}).get('userBookings', []),
                user_certificates=request_data.get('context', {}).get('userCertificates', [])
            )
            reasoning_chain.append(
                f"Context: {len(context.user_bookings)} bookings, "
                f"{len(context.user_certificates)} certificates"
            )
            
            # Step 4: Call GPT (if not blocked by sensitivity)
            gpt_response = None
            gpt_tokens = 0
            
            if not sensitivity.should_block:
                gpt_response = self.gpt_client.call_gpt(
                    email=request_data,
                    context=context,
                    system_prompt=self.system_prompt
                )
                
                if gpt_response:
                    reasoning_chain.append(
                        f"GPT: confidence={gpt_response.confidence:.2f}, "
                        f"action={gpt_response.action}"
                    )
                    email_db.log_processing_step(
                        record_id, 'INFO', 'gpt',
                        'GPT analysis complete',
                        {
                            'confidence': gpt_response.confidence,
                            'action': gpt_response.action,
                            'category': gpt_response.enquiry_type
                        }
                    )
                else:
                    reasoning_chain.append("GPT: API call failed")
                    email_db.log_processing_step(
                        record_id, 'ERROR', 'gpt',
                        'GPT API call failed'
                    )
            else:
                reasoning_chain.append("GPT: Skipped due to sensitivity flags")
                email_db.log_processing_step(
                    record_id, 'WARNING', 'gpt',
                    'GPT skipped due to sensitivity flags'
                )
            
            # Step 5: Make final decision
            decision = self._make_decision(
                filter_result=filter_result,
                sensitivity=sensitivity,
                gpt_response=gpt_response,
                reasoning_chain=reasoning_chain
            )
            
            email_db.log_processing_step(
                record_id, 'INFO', 'decision',
                f'Final decision: respond={decision.should_respond}, confidence={decision.confidence:.2f}',
                {
                    'should_respond': decision.should_respond,
                    'confidence': decision.confidence,
                    'action': decision.action
                }
            )
            
            # Step 6: Build response
            api_response = self._build_response(
                decision=decision,
                gpt_response=gpt_response,
                context=context,
                reasoning_chain=reasoning_chain,
                processing_time=time.time() - start_time
            )
            
            # Update database with final result
            decision_dict = asdict(decision)
            decision_dict['humanReview'] = api_response.human_review
            
            email_db.update_processing_result(
                record_id,
                decision_dict,
                api_response.processing_time,
                gpt_tokens=gpt_tokens
            )
            
            # Save response if generated
            if api_response.response:
                email_db.save_response(
                    record_id,
                    api_response.response,
                    api_response.actions
                )
            
            logger.info(
                f"Processing complete: confidence={decision.confidence:.2f}, "
                f"action={decision.action}, time={api_response.processing_time:.2f}s"
            )
            
            return asdict(api_response)
            
        except Exception as e:
            logger.error(f"Error processing email: {e}")
            logger.error(traceback.format_exc())
            
            # Log error to database
            if record_id:
                email_db.log_error(record_id, str(e))
                email_db.log_processing_step(
                    record_id, 'ERROR', 'exception',
                    f'Processing failed: {str(e)}'
                )
            
            return self._build_error_response(
                error_msg=str(e),
                reasoning_chain=reasoning_chain,
                processing_time=time.time() - start_time
            )
    
    def _make_decision(
        self,
        filter_result: FilterResult,
        sensitivity: SensitivityResult,
        gpt_response: Optional[GPTResponse],
        reasoning_chain: List[str]
    ) -> ProcessingDecision:
        """
        Make final decision about email handling.
        
        Args:
            filter_result: Pre-filter result
            sensitivity: Sensitivity detection result
            gpt_response: GPT analysis result (may be None)
            reasoning_chain: Running list of reasoning steps
            
        Returns:
            ProcessingDecision object
        """
        logger.info("Making final decision...")
        
        # Determine final confidence (lowest of all constraints)
        confidence = 0.5  # Default
        
        if filter_result.skip_gpt:
            confidence = filter_result.confidence
        elif gpt_response:
            confidence = gpt_response.confidence
        
        # Apply sensitivity constraints
        if sensitivity.flags:
            confidence = min(confidence, sensitivity.max_confidence)
            reasoning_chain.append(
                f"Confidence capped at {sensitivity.max_confidence:.2f} "
                f"due to sensitivity"
            )
        
        # Determine if we should respond
        should_respond = (
            confidence >= CONFIDENCE_THRESHOLD_MODERATE and
            not sensitivity.should_block and
            not filter_result.skip_gpt
        )
        
        # Determine action
        action = "none"
        if gpt_response and confidence >= CONFIDENCE_THRESHOLD_HIGH:
            action = gpt_response.action
        
        # Block certain actions if sensitivity detected
        if sensitivity.flags and action != "none":
            logger.warning(
                f"Blocking action '{action}' due to sensitivity flags: "
                f"{sensitivity.flags}"
            )
            action = "none"
            reasoning_chain.append("Action blocked due to sensitivity")
        
        # Determine category
        category = filter_result.category
        if gpt_response:
            category = gpt_response.enquiry_type
        
        logger.info(
            f"Decision: respond={should_respond}, confidence={confidence:.2f}, "
            f"action={action}"
        )
        
        return ProcessingDecision(
            should_respond=should_respond,
            confidence=confidence,
            category=category,
            action=action,
            reasoning_chain=reasoning_chain,
            sensitivity_flags=sensitivity.flags
        )
    
    def _build_response(
        self,
        decision: ProcessingDecision,
        gpt_response: Optional[GPTResponse],
        context: EmailContext,
        reasoning_chain: List[str],
        processing_time: float
    ) -> APIResponse:
        """
        Build complete API response.
        
        Args:
            decision: Processing decision
            gpt_response: GPT response (may be None)
            context: Email context
            reasoning_chain: Processing reasoning
            processing_time: Total processing time
            
        Returns:
            Complete APIResponse object
        """
        logger.info("Building API response...")
        
        # Build response object (if we should respond)
        response_obj = None
        actions = []
        
        if decision.should_respond and gpt_response:
            # Determine template and variables
            template_id, variables = self._select_template(
                decision=decision,
                gpt_response=gpt_response,
                context=context
            )
            
            # Generate response body
            body = self.template_engine.generate_response(template_id, variables)
            
            response_obj = {
                'templateId': template_id,
                'subject': f"Re: {gpt_response.enquiry_type}",
                'bodyHtml': body,
                'variables': variables
            }
            
            # Build actions list
            actions.append({
                'type': 'send_email',
                'bodyHtml': body
            })
            
            # Add certificate attachment if needed
            if decision.action == 'send_certificate' and context.user_certificates:
                for cert in context.user_certificates[:1]:  # Just first one for now
                    actions.append({
                        'type': 'attach_certificate',
                        'certificateUrl': cert.get('certificateUrl', '')
                    })
            
            # Add cancellation action if needed
            if decision.action == 'cancel' and context.user_bookings:
                booking = context.user_bookings[0]
                actions.append({
                    'type': 'cancel_booking',
                    'bookingId': booking.get('bookingId', '')
                })
        
        # Determine if human review required
        human_review = {
            'required': (
                not decision.should_respond or
                decision.confidence < CONFIDENCE_THRESHOLD_MODERATE or
                len(decision.sensitivity_flags) > 0
            ),
            'priority': 'high' if decision.sensitivity_flags else 'normal',
            'reason': (
                '; '.join(decision.sensitivity_flags) if decision.sensitivity_flags
                else 'Low confidence' if decision.confidence < CONFIDENCE_THRESHOLD_MODERATE
                else None
            )
        }
        
        # Build metadata
        metadata = {
            'apiVersion': '2.0',
            'processingNode': os.getenv('HOSTNAME', 'unknown'),
            'gptTokensUsed': 0,  # Would track from GPT response
            'cacheHit': False
        }
        
        return APIResponse(
            success=True,
            processing_time=processing_time,
            decision=decision,
            response=response_obj,
            actions=actions,
            human_review=human_review,
            metadata=metadata
        )
    
    def _select_template(
        self,
        decision: ProcessingDecision,
        gpt_response: GPTResponse,
        context: EmailContext
    ) -> tuple:
        """
        Select appropriate template and build variables.
        
        Args:
            decision: Processing decision
            gpt_response: GPT response
            context: Email context
            
        Returns:
            Tuple of (template_id, variables_dict)
        """
        # Default variables
        variables = {
            'firstName': gpt_response.sender_first_name or 'there'
        }
        
        # Certificate request
        if 'certificate' in decision.action and context.user_certificates:
            cert = context.user_certificates[0]
            template_id = 'certificate_found'
            variables.update({
                'courseName': cert.get('course', 'Unknown Course'),
                'courseDate': cert.get('date', 'Unknown Date')
            })
        elif 'certificate' in decision.category:
            template_id = 'certificate_not_found'
        
        # Cancellation
        elif decision.action == 'cancel' and context.user_bookings:
            booking = context.user_bookings[0]
            template_id = 'cancellation_confirmed'
            variables.update({
                'courseName': booking.get('course', 'Unknown Course'),
                'courseDate': booking.get('date', 'Unknown Date'),
                'courseTime': booking.get('startTime', 'Unknown Time'),
                'courseVenue': booking.get('venue', 'Unknown Venue')
            })
        
        # General availability
        else:
            template_id = 'course_availability'
        
        logger.info(f"Selected template: {template_id}")
        
        return template_id, variables
    
    def _build_filtered_response(
        self,
        filter_result: FilterResult,
        reasoning_chain: List[str],
        processing_time: float
    ) -> Dict[str, Any]:
        """Build response for filtered (skipped) emails."""
        decision = ProcessingDecision(
            should_respond=False,
            confidence=filter_result.confidence,
            category=filter_result.category,
            action='none',
            reasoning_chain=reasoning_chain,
            sensitivity_flags=[]
        )
        
        response = APIResponse(
            success=True,
            processing_time=processing_time,
            decision=decision,
            response=None,
            actions=[],
            human_review={
                'required': False,
                'priority': 'low',
                'reason': filter_result.reason
            },
            metadata={
                'apiVersion': '2.0',
                'filtered': True,
                'filterReason': filter_result.reason
            }
        )
        
        return asdict(response)
    
    def _build_error_response(
        self,
        error_msg: str,
        reasoning_chain: List[str],
        processing_time: float
    ) -> Dict[str, Any]:
        """Build response for processing errors."""
        return {
            'success': False,
            'error': {
                'code': 'PROCESSING_ERROR',
                'message': error_msg,
                'details': '\n'.join(reasoning_chain),
                'retryable': True
            },
            'fallback': {
                'shouldRespond': False,
                'humanReview': {
                    'required': True,
                    'priority': 'high',
                    'reason': f'API processing failed: {error_msg}'
                }
            },
            'metadata': {
                'processingTime': processing_time
            }
        }
    
    def _load_system_prompt(self) -> str:
        """Load GPT system prompt (simplified version)."""
        # In production, load from file
        # For now, return inline version
        return """
You are REdI-AI, an automated email assistant for the Resuscitation Education Initiative.

Analyze emails and respond with JSON containing:
- is_new_email: boolean
- sender_first_name: string
- enquiry_type: string (1-3 words)
- recommended_response: string
- confidence: number (0-1)
- action: "send_certificate" | "cancel" | "none"

Confidence scoring:
- 0.1-0.2: System messages, complaints, urgent matters
- 0.5-0.7: General enquiries, needs clarification
- 0.8-0.95: Clear actionable requests

NEVER respond to: complaints, escalations, HR issues, negative sentiment.
Always include booking app link: https://tinyurl.com/bookREdIALS
"""


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'version': '2.0',
        'timestamp': datetime.utcnow().isoformat(),
        'database': 'connected'
    })


@app.route('/api/statistics', methods=['GET'])
@require_api_key
def get_statistics():
    """
    Get processing statistics.
    
    Query Parameters:
        days: Number of days to include (default: 30)
    """
    try:
        days = int(request.args.get('days', 30))
        stats = email_db.get_statistics(days=days)
        
        return jsonify({
            'success': True,
            'statistics': stats
        })
        
    except Exception as e:
        logger.error(f"Statistics endpoint error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/recent-emails', methods=['GET'])
@require_api_key
def get_recent_emails():
    """
    Get recent email records.
    
    Query Parameters:
        limit: Maximum number of records (default: 50)
    """
    try:
        limit = int(request.args.get('limit', 50))
        emails = email_db.get_recent_emails(limit=limit)
        
        return jsonify({
            'success': True,
            'count': len(emails),
            'emails': emails
        })
        
    except Exception as e:
        logger.error(f"Recent emails endpoint error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/process-email', methods=['POST'])
@require_api_key
def process_email():
    """
    Main email processing endpoint.
    
    Accepts email data, processes it, and returns decision.
    """
    try:
        request_data = request.json
        
        if not request_data:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'INVALID_REQUEST',
                    'message': 'Request body required'
                }
            }), 400
        
        # Process email
        processor = EmailProcessor()
        result = processor.process(request_data)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Endpoint error: {e}")
        logger.error(traceback.format_exc())
        
        return jsonify({
            'success': False,
            'error': {
                'code': 'INTERNAL_ERROR',
                'message': str(e)
            }
        }), 500


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    logger.info("Starting REdI Email Processing API Server...")
    logger.info(f"Model: {OPENAI_MODEL}")
    logger.info(f"Confidence thresholds: High={CONFIDENCE_THRESHOLD_HIGH}, "
                f"Moderate={CONFIDENCE_THRESHOLD_MODERATE}, "
                f"Low={CONFIDENCE_THRESHOLD_LOW}")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    )
