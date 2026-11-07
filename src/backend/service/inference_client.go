package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"

	"chat-app/backend/model"
)

var (
	ErrInferenceConnection = errors.New("inference API connection failed")
	ErrInferenceTimeout    = errors.New("inference API request timed out")
	ErrInferenceResponse   = errors.New("inference API returned an invalid response")
)

type InferenceHTTPError struct {
	StatusCode int
	Detail     string
}

func (e *InferenceHTTPError) Error() string {
	return fmt.Sprintf("inference API returned HTTP %d: %s", e.StatusCode, e.Detail)
}

type ModelStatus struct {
	ModelID *string `json:"model_id"`
	Name    *string `json:"name"`
	Status  string  `json:"status"`
	Error   string  `json:"error,omitempty"`
}

type InferenceClient struct {
	baseURL    string
	httpClient *http.Client
}

func NewInferenceClient(baseURL string, timeout time.Duration) *InferenceClient {
	if timeout <= 0 {
		timeout = 90 * time.Second
	}
	return &InferenceClient{
		baseURL: strings.TrimRight(baseURL, "/"),
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}

func (c *InferenceClient) Generate(
	systemPrompt string,
	history []model.Message,
	input string,
) (string, error) {
	request := struct {
		SystemPrompt string          `json:"system_prompt"`
		History      []model.Message `json:"history"`
		UserInput    string          `json:"user_input"`
	}{
		SystemPrompt: systemPrompt,
		History:      history,
		UserInput:    input,
	}
	body, err := c.postJSON("/generate", request)
	if err != nil {
		return "", err
	}

	var response struct {
		Text *string `json:"text"`
	}
	if err := json.Unmarshal(body, &response); err != nil || response.Text == nil {
		return "", fmt.Errorf("%w: generate response must contain text", ErrInferenceResponse)
	}
	return *response.Text, nil
}

func (c *InferenceClient) CurrentModel() (ModelStatus, error) {
	body, err := c.getJSON("/models/current")
	if err != nil {
		return ModelStatus{}, err
	}

	var response ModelStatus
	if err := json.Unmarshal(body, &response); err != nil || response.Status == "" {
		return ModelStatus{}, fmt.Errorf("%w: model status is missing or malformed", ErrInferenceResponse)
	}
	return response, nil
}

func (c *InferenceClient) postJSON(path string, payload any) ([]byte, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("encode inference request: %w", err)
	}
	request, err := http.NewRequest(http.MethodPost, c.baseURL+path, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create inference request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	return c.do(request)
}

func (c *InferenceClient) getJSON(path string) ([]byte, error) {
	request, err := http.NewRequest(http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return nil, fmt.Errorf("create inference request: %w", err)
	}
	return c.do(request)
}

func (c *InferenceClient) do(request *http.Request) ([]byte, error) {
	response, err := c.httpClient.Do(request)
	if err != nil {
		var networkError net.Error
		if errors.Is(err, context.DeadlineExceeded) ||
			(errors.As(err, &networkError) && networkError.Timeout()) {
			return nil, fmt.Errorf("%w: %v", ErrInferenceTimeout, err)
		}
		return nil, fmt.Errorf("%w: %v", ErrInferenceConnection, err)
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, fmt.Errorf("%w: read response: %v", ErrInferenceResponse, err)
	}
	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		var errorBody struct {
			Detail string `json:"detail"`
		}
		_ = json.Unmarshal(body, &errorBody)
		if errorBody.Detail == "" {
			errorBody.Detail = strings.TrimSpace(string(body))
		}
		return nil, &InferenceHTTPError{
			StatusCode: response.StatusCode,
			Detail:     errorBody.Detail,
		}
	}
	return body, nil
}
