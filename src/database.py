"""
REdI Email Processing API - Database Module
===========================================

Handles database connections, models, and logging operations.

Author: Sean Wing
Date: 2026-01-02
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
import json

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager

logger = logging.getLogger(__name__)


# ============================================================================
# DATABASE CONNECTION POOL
# ============================================================================

class DatabasePool:
    """
    PostgreSQL connection pool for efficient database operations.
    
    Uses connection pooling to avoid creating new connections for each request.
    """
    
    def __init__(self, database_url: str, min_conn: int = 1, max_conn: int = 10):
        """
        Initialize database connection pool.
        
        Args:
            database_url: PostgreSQL connection string
            min_conn: Minimum number of connections
            max_conn: Maximum number of connections
        """
        self.database_url = database_url
        self.pool = None
        
        try:
            self.pool = SimpleConnectionPool(
                min_conn,
                max_conn,
                database_url
            )
            logger.info(f"Database pool initialized: {min_conn}-{max_conn} connections")
            
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """
        Get a connection from the pool.
        
        Yields:
            Database connection
        """
        conn = self.pool.getconn()
        try:
            yield conn
        finally:
            self.pool.putconn(conn)
    
    @contextmanager
    def get_cursor(self, commit: bool = True):
        """
        Get a cursor from the pool with automatic commit/rollback.
        
        Args:
            commit: Whether to auto-commit on success
            
        Yields:
            Database cursor
        """
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                yield cursor
                if commit:
                    conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Database error: {e}")
                raise
            finally:
                cursor.close()
    
    def close(self):
        """Close all connections in the pool."""
        if self.pool:
            self.pool.closeall()
            logger.info("Database pool closed")


# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

class EmailDatabase:
    """
    Database operations for email processing records.
    
    Provides methods to:
    - Create email records
    - Update processing results
    - Log processing steps
    - Query statistics
    """
    
    def __init__(self, pool: DatabasePool):
        """
        Initialize database operations.
        
        Args:
            pool: Database connection pool
        """
        self.pool = pool
        logger.info("EmailDatabase initialized")
    
    def create_email_record(
        self,
        email_data: Dict[str, Any],
        context: Dict[str, Any]
    ) -> str:
        """
        Create initial email record in database.
        
        Args:
            email_data: Email data from request
            context: User context (bookings, certificates)
            
        Returns:
            UUID of created record
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO email_records (
                        email_id,
                        conversation_id,
                        received_datetime,
                        sender_name,
                        sender_email,
                        subject,
                        body_preview,
                        body_text,
                        body_html,
                        user_bookings_count,
                        user_certificates_count
                    ) VALUES (
                        %(email_id)s,
                        %(conversation_id)s,
                        %(received_datetime)s,
                        %(sender_name)s,
                        %(sender_email)s,
                        %(subject)s,
                        %(body_preview)s,
                        %(body_text)s,
                        %(body_html)s,
                        %(user_bookings_count)s,
                        %(user_certificates_count)s
                    )
                    RETURNING id::text
                """, {
                    'email_id': email_data.get('emailId', 'unknown'),
                    'conversation_id': email_data.get('conversationId'),
                    'received_datetime': email_data.get('receivedDateTime', datetime.utcnow().isoformat()),
                    'sender_name': email_data.get('from', {}).get('name'),
                    'sender_email': email_data.get('from', {}).get('email', 'unknown'),
                    'subject': email_data.get('subject'),
                    'body_preview': email_data.get('bodyPreview'),
                    'body_text': email_data.get('bodyText'),
                    'body_html': email_data.get('bodyHtml'),
                    'user_bookings_count': len(context.get('userBookings', [])),
                    'user_certificates_count': len(context.get('userCertificates', []))
                })
                
                record_id = cursor.fetchone()['id']
                logger.info(f"Created email record: {record_id}")
                return record_id
                
        except Exception as e:
            logger.error(f"Failed to create email record: {e}")
            raise
    
    def update_processing_result(
        self,
        record_id: str,
        decision: Dict[str, Any],
        processing_time: float,
        gpt_tokens: int = 0,
        pre_filter_reason: Optional[str] = None,
        skipped_gpt: bool = False
    ):
        """
        Update email record with processing results.
        
        Args:
            record_id: UUID of email record
            decision: Processing decision dictionary
            processing_time: Time taken to process (seconds)
            gpt_tokens: Number of GPT tokens used
            pre_filter_reason: Reason if pre-filtered
            skipped_gpt: Whether GPT was skipped
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE email_records SET
                        category = %(category)s,
                        confidence = %(confidence)s,
                        action = %(action)s,
                        should_respond = %(should_respond)s,
                        sensitivity_flags = %(sensitivity_flags)s,
                        pre_filter_reason = %(pre_filter_reason)s,
                        skipped_gpt = %(skipped_gpt)s,
                        processing_time_seconds = %(processing_time)s,
                        gpt_tokens_used = %(gpt_tokens)s,
                        human_review_required = %(human_review_required)s,
                        human_review_priority = %(human_review_priority)s,
                        human_review_reason = %(human_review_reason)s,
                        api_version = '2.0'
                    WHERE id = %(record_id)s::uuid
                """, {
                    'record_id': record_id,
                    'category': decision.get('category'),
                    'confidence': decision.get('confidence'),
                    'action': decision.get('action'),
                    'should_respond': decision.get('shouldRespond', False),
                    'sensitivity_flags': decision.get('sensitivityFlags', []),
                    'pre_filter_reason': pre_filter_reason,
                    'skipped_gpt': skipped_gpt,
                    'processing_time': processing_time,
                    'gpt_tokens': gpt_tokens,
                    'human_review_required': decision.get('humanReview', {}).get('required', False),
                    'human_review_priority': decision.get('humanReview', {}).get('priority'),
                    'human_review_reason': decision.get('humanReview', {}).get('reason')
                })
                
                logger.info(f"Updated processing result for record: {record_id}")
                
        except Exception as e:
            logger.error(f"Failed to update processing result: {e}")
            # Don't raise - we don't want DB errors to break the API response
    
    def save_response(
        self,
        record_id: str,
        response_data: Dict[str, Any],
        actions: List[Dict[str, Any]]
    ):
        """
        Save email response details.
        
        Args:
            record_id: UUID of email record
            response_data: Response content and metadata
            actions: List of actions to be performed
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO email_responses (
                        email_record_id,
                        subject,
                        body_html,
                        template_id,
                        template_variables,
                        actions_performed
                    ) VALUES (
                        %(record_id)s::uuid,
                        %(subject)s,
                        %(body_html)s,
                        %(template_id)s,
                        %(template_variables)s,
                        %(actions_performed)s
                    )
                    ON CONFLICT (email_record_id) DO UPDATE SET
                        subject = EXCLUDED.subject,
                        body_html = EXCLUDED.body_html,
                        template_id = EXCLUDED.template_id,
                        template_variables = EXCLUDED.template_variables,
                        actions_performed = EXCLUDED.actions_performed
                """, {
                    'record_id': record_id,
                    'subject': response_data.get('subject'),
                    'body_html': response_data.get('bodyHtml'),
                    'template_id': response_data.get('templateId'),
                    'template_variables': Json(response_data.get('variables', {})),
                    'actions_performed': Json(actions)
                })
                
                logger.info(f"Saved response for record: {record_id}")
                
        except Exception as e:
            logger.error(f"Failed to save response: {e}")
            # Don't raise - we don't want DB errors to break the API response
    
    def log_processing_step(
        self,
        record_id: str,
        level: str,
        step: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log a processing step to database.
        
        Args:
            record_id: UUID of email record
            level: Log level (INFO, WARNING, ERROR)
            step: Processing step name
            message: Log message
            metadata: Additional metadata
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO processing_logs (
                        email_record_id,
                        log_level,
                        step,
                        message,
                        metadata
                    ) VALUES (
                        %(record_id)s::uuid,
                        %(level)s,
                        %(step)s,
                        %(message)s,
                        %(metadata)s
                    )
                """, {
                    'record_id': record_id,
                    'level': level,
                    'step': step,
                    'message': message,
                    'metadata': Json(metadata) if metadata else None
                })
                
        except Exception as e:
            logger.error(f"Failed to log processing step: {e}")
            # Don't raise - logging failures shouldn't break processing
    
    def log_error(
        self,
        record_id: str,
        error_message: str
    ):
        """
        Mark email record as having processing error.
        
        Args:
            record_id: UUID of email record
            error_message: Error message
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE email_records SET
                        processing_error = TRUE,
                        error_message = %(error_message)s
                    WHERE id = %(record_id)s::uuid
                """, {
                    'record_id': record_id,
                    'error_message': error_message
                })
                
                logger.warning(f"Logged error for record {record_id}: {error_message}")
                
        except Exception as e:
            logger.error(f"Failed to log error: {e}")
    
    def mark_response_sent(self, record_id: str):
        """
        Mark that response has been sent for this email.
        
        Args:
            record_id: UUID of email record
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE email_records SET
                        response_sent = TRUE,
                        response_sent_at = NOW()
                    WHERE id = %(record_id)s::uuid
                """, {
                    'record_id': record_id
                })
                
                logger.info(f"Marked response sent for record: {record_id}")
                
        except Exception as e:
            logger.error(f"Failed to mark response sent: {e}")
    
    def get_statistics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get processing statistics for the last N days.
        
        Args:
            days: Number of days to include
            
        Returns:
            Dictionary of statistics
        """
        try:
            with self.pool.get_cursor() as cursor:
                # Overall stats
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_emails,
                        COUNT(*) FILTER (WHERE should_respond = TRUE) as responses_sent,
                        COUNT(*) FILTER (WHERE skipped_gpt = TRUE) as pre_filtered,
                        COUNT(*) FILTER (WHERE human_review_required = TRUE) as human_reviews,
                        AVG(confidence) as avg_confidence,
                        AVG(processing_time_seconds) as avg_processing_time,
                        SUM(gpt_tokens_used) as total_gpt_tokens
                    FROM email_records
                    WHERE received_datetime >= NOW() - INTERVAL '%s days'
                """, (days,))
                
                overall = dict(cursor.fetchone())
                
                # Category breakdown
                cursor.execute("""
                    SELECT 
                        category,
                        COUNT(*) as count,
                        AVG(confidence) as avg_confidence
                    FROM email_records
                    WHERE received_datetime >= NOW() - INTERVAL '%s days'
                        AND category IS NOT NULL
                    GROUP BY category
                    ORDER BY count DESC
                    LIMIT 10
                """, (days,))
                
                categories = [dict(row) for row in cursor.fetchall()]
                
                return {
                    'period_days': days,
                    'overall': overall,
                    'categories': categories
                }
                
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def get_recent_emails(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent email records.
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            List of email record dictionaries
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        id::text,
                        email_id,
                        received_datetime,
                        sender_email,
                        subject,
                        category,
                        confidence,
                        action,
                        should_respond,
                        sensitivity_flags,
                        human_review_required,
                        processing_time_seconds,
                        created_at
                    FROM email_records
                    ORDER BY received_datetime DESC
                    LIMIT %s
                """, (limit,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Failed to get recent emails: {e}")
            return []


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def init_database_pool(database_url: Optional[str] = None) -> DatabasePool:
    """
    Initialize database connection pool from environment.
    
    Args:
        database_url: Database connection string (optional, reads from env)
        
    Returns:
        Initialized DatabasePool
    """
    if not database_url:
        database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")
    
    logger.info(f"Initializing database connection...")
    
    return DatabasePool(database_url)
