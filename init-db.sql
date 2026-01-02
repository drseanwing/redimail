-- REdI Email Processing Database Schema
-- Author: Sean Wing
-- Date: 2026-01-02

-- Create extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Email Processing Records Table
CREATE TABLE IF NOT EXISTS email_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Email Identifiers
    email_id VARCHAR(255) UNIQUE NOT NULL,
    conversation_id VARCHAR(255),
    
    -- Email Metadata
    received_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
    processed_datetime TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Sender Information
    sender_name VARCHAR(255),
    sender_email VARCHAR(255) NOT NULL,
    
    -- Email Content
    subject TEXT,
    body_preview TEXT,
    body_text TEXT,
    body_html TEXT,
    
    -- Processing Results
    category VARCHAR(100),
    confidence DECIMAL(3,2),
    action VARCHAR(50),
    should_respond BOOLEAN DEFAULT FALSE,
    
    -- Sensitivity & Flags
    sensitivity_flags TEXT[], -- Array of flags
    pre_filter_reason VARCHAR(100),
    skipped_gpt BOOLEAN DEFAULT FALSE,
    
    -- Context
    user_bookings_count INTEGER DEFAULT 0,
    user_certificates_count INTEGER DEFAULT 0,
    
    -- Processing Metadata
    processing_time_seconds DECIMAL(6,3),
    gpt_tokens_used INTEGER,
    api_version VARCHAR(20),
    
    -- Human Review
    human_review_required BOOLEAN DEFAULT FALSE,
    human_review_priority VARCHAR(20),
    human_review_reason TEXT,
    human_reviewed_at TIMESTAMP WITH TIME ZONE,
    human_reviewed_by VARCHAR(255),
    
    -- Response Details
    response_template_id VARCHAR(100),
    response_sent BOOLEAN DEFAULT FALSE,
    response_sent_at TIMESTAMP WITH TIME ZONE,
    
    -- Error Tracking
    processing_error BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    
    -- Audit Fields
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Response Details Table (one-to-one with email_records)
CREATE TABLE IF NOT EXISTS email_responses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email_record_id UUID REFERENCES email_records(id) ON DELETE CASCADE,
    
    -- Response Content
    subject TEXT,
    body_html TEXT,
    body_text TEXT,
    template_id VARCHAR(100),
    
    -- Variables used in template
    template_variables JSONB,
    
    -- Actions taken
    actions_performed JSONB, -- Array of action objects
    
    -- Attachments
    attachments JSONB, -- Array of attachment info
    
    -- Audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(email_record_id)
);

-- Processing Log Table (for detailed reasoning chain)
CREATE TABLE IF NOT EXISTS processing_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email_record_id UUID REFERENCES email_records(id) ON DELETE CASCADE,
    
    -- Log Entry
    log_level VARCHAR(20) NOT NULL, -- INFO, WARNING, ERROR
    step VARCHAR(100) NOT NULL,      -- pre_filter, sensitivity, gpt, decision
    message TEXT NOT NULL,
    
    -- Additional Data
    metadata JSONB,
    
    -- Timestamp
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_email_records_email_id ON email_records(email_id);
CREATE INDEX idx_email_records_sender_email ON email_records(sender_email);
CREATE INDEX idx_email_records_received_datetime ON email_records(received_datetime DESC);
CREATE INDEX idx_email_records_category ON email_records(category);
CREATE INDEX idx_email_records_confidence ON email_records(confidence);
CREATE INDEX idx_email_records_human_review ON email_records(human_review_required) WHERE human_review_required = TRUE;
CREATE INDEX idx_email_records_created_at ON email_records(created_at DESC);

CREATE INDEX idx_email_responses_email_record_id ON email_responses(email_record_id);

CREATE INDEX idx_processing_logs_email_record_id ON processing_logs(email_record_id);
CREATE INDEX idx_processing_logs_created_at ON processing_logs(created_at DESC);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to automatically update updated_at
CREATE TRIGGER update_email_records_updated_at 
    BEFORE UPDATE ON email_records 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Statistics View
CREATE OR REPLACE VIEW email_statistics AS
SELECT 
    DATE(received_datetime) as date,
    COUNT(*) as total_emails,
    COUNT(*) FILTER (WHERE should_respond = TRUE) as responses_sent,
    COUNT(*) FILTER (WHERE skipped_gpt = TRUE) as pre_filtered,
    COUNT(*) FILTER (WHERE human_review_required = TRUE) as human_reviews,
    AVG(confidence) as avg_confidence,
    AVG(processing_time_seconds) as avg_processing_time,
    SUM(gpt_tokens_used) as total_gpt_tokens
FROM email_records
GROUP BY DATE(received_datetime)
ORDER BY date DESC;

-- Category Statistics View
CREATE OR REPLACE VIEW category_statistics AS
SELECT 
    category,
    COUNT(*) as total_count,
    AVG(confidence) as avg_confidence,
    COUNT(*) FILTER (WHERE should_respond = TRUE) as response_count,
    COUNT(*) FILTER (WHERE human_review_required = TRUE) as review_count
FROM email_records
WHERE category IS NOT NULL
GROUP BY category
ORDER BY total_count DESC;

-- Sensitivity Flags View
CREATE OR REPLACE VIEW sensitivity_statistics AS
SELECT 
    unnest(sensitivity_flags) as flag,
    COUNT(*) as count,
    AVG(confidence) as avg_confidence
FROM email_records
WHERE sensitivity_flags IS NOT NULL AND array_length(sensitivity_flags, 1) > 0
GROUP BY flag
ORDER BY count DESC;

-- Grant permissions (adjust as needed)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO redi;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO redi;

-- Insert initial test record (optional)
-- INSERT INTO email_records (
--     email_id, sender_email, subject, received_datetime, category, confidence
-- ) VALUES (
--     'test-initial-record', 'test@example.com', 'Test Email', NOW(), 'test', 0.5
-- );

COMMIT;
