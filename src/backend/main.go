package main

import (
	"errors"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/labstack/echo/v5"

	"chat-app/backend/model"
	"chat-app/backend/service"
	"chat-app/backend/store"
)

const sessionCookieName = "session_id"

func newServer() *echo.Echo {
	inferenceClient := service.NewInferenceClient(inferenceAPIURL(), 90*time.Second)
	return newServerWithDependencies(store.NewSessionStore(), inferenceClient)
}

func inferenceAPIURL() string {
	if url := strings.TrimSpace(os.Getenv("INFERENCE_API_URL")); url != "" {
		return strings.TrimRight(url, "/")
	}
	return "http://127.0.0.1:8001"
}

func newServerWithDependencies(
	sessions *store.SessionStore,
	inferenceClient *service.InferenceClient,
) *echo.Echo {
	e := echo.New()

	e.GET("/health", func(c *echo.Context) error {
		return c.JSON(http.StatusOK, map[string]string{"status": "ok"})
	})
	e.POST("/api/session", func(c *echo.Context) error {
		if cookie, err := c.Request().Cookie(sessionCookieName); err == nil {
			if _, ok := sessions.Get(cookie.Value); ok {
				return c.JSON(http.StatusOK, map[string]bool{"success": true})
			}
		}

		session, err := sessions.Create()
		if err != nil {
			return err
		}
		http.SetCookie(c.Response(), &http.Cookie{
			Name:     sessionCookieName,
			Value:    session.ID,
			Path:     "/",
			HttpOnly: true,
			Secure:   c.Request().TLS != nil,
			SameSite: http.SameSiteLaxMode,
		})
		return c.JSON(http.StatusCreated, map[string]bool{"success": true})
	})

	e.POST("/api/chat", func(c *echo.Context) error {
		sessionID, ok := getSessionID(c)
		if !ok {
			return writeAPIError(c, http.StatusUnauthorized, "valid session cookie is required")
		}

		var request struct {
			Message string `json:"message"`
		}
		if err := c.Bind(&request); err != nil {
			return writeAPIError(c, http.StatusBadRequest, "invalid request body")
		}
		if strings.TrimSpace(request.Message) == "" {
			return writeAPIError(c, http.StatusBadRequest, "message is required")
		}

		response, err := service.SendMessage(
			sessions,
			sessionID,
			request.Message,
			inferenceClient.Generate,
		)
		if errors.Is(err, service.ErrSessionNotFound) {
			return writeAPIError(c, http.StatusUnauthorized, "valid session cookie is required")
		}
		if err != nil {
			return writeAPIError(c, inferenceHTTPStatus(err), err.Error())
		}
		return c.JSON(http.StatusOK, map[string]string{"response": response})
	})

	e.GET("/api/history", func(c *echo.Context) error {
		session, ok := getSession(c, sessions)
		if !ok {
			return writeAPIError(c, http.StatusUnauthorized, "valid session cookie is required")
		}
		if session.History == nil {
			session.History = []model.Message{}
		}
		return c.JSON(http.StatusOK, map[string][]model.Message{"history": session.History})
	})

	e.POST("/api/reset", func(c *echo.Context) error {
		sessionID, ok := getSessionID(c)
		if !ok {
			return writeAPIError(c, http.StatusUnauthorized, "valid session cookie is required")
		}
		if !sessions.ResetHistory(sessionID) {
			return writeAPIError(c, http.StatusUnauthorized, "valid session cookie is required")
		}
		return c.JSON(http.StatusOK, map[string]bool{"success": true})
	})

	e.PUT("/api/system-prompt", func(c *echo.Context) error {
		sessionID, ok := getSessionID(c)
		if !ok {
			return writeAPIError(c, http.StatusUnauthorized, "valid session cookie is required")
		}
		var request struct {
			SystemPrompt string `json:"system_prompt"`
		}
		if err := c.Bind(&request); err != nil {
			return writeAPIError(c, http.StatusBadRequest, "invalid request body")
		}
		if !sessions.UpdateSystemPrompt(sessionID, request.SystemPrompt) {
			return writeAPIError(c, http.StatusUnauthorized, "valid session cookie is required")
		}
		return c.JSON(http.StatusOK, map[string]bool{"success": true})
	})

	e.GET("/api/models/current", func(c *echo.Context) error {
		if _, ok := getSession(c, sessions); !ok {
			return writeAPIError(c, http.StatusUnauthorized, "valid session cookie is required")
		}
		status, err := inferenceClient.CurrentModel()
		if err != nil {
			return writeAPIError(c, inferenceHTTPStatus(err), err.Error())
		}
		return c.JSON(http.StatusOK, status)
	})
	e.Static("/", "../frontend")
	return e
}

func getSessionID(c *echo.Context) (string, bool) {
	cookie, err := c.Request().Cookie(sessionCookieName)
	if err != nil || cookie.Value == "" {
		return "", false
	}
	return cookie.Value, true
}

func getSession(c *echo.Context, sessions *store.SessionStore) (*model.Session, bool) {
	sessionID, ok := getSessionID(c)
	if !ok {
		return nil, false
	}
	return sessions.Get(sessionID)
}

func writeAPIError(c *echo.Context, status int, message string) error {
	return c.JSON(status, map[string]string{"error": message})
}

func inferenceHTTPStatus(err error) int {
	if errors.Is(err, service.ErrInferenceTimeout) {
		return http.StatusGatewayTimeout
	}
	var responseError *service.InferenceHTTPError
	if errors.As(err, &responseError) {
		if responseError.StatusCode == http.StatusServiceUnavailable {
			return http.StatusServiceUnavailable
		}
		return http.StatusBadGateway
	}
	return http.StatusBadGateway
}

func main() {
	if err := newServer().Start("127.0.0.1:8000"); err != nil && err != http.ErrServerClosed {
		panic(err)
	}
}
