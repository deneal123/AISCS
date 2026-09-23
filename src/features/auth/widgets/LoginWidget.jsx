import React, { useEffect, useRef, useState } from "react";
import { Button, Divider, HStack, Icon, Link, Text, VStack } from "@chakra-ui/react";
import { Link as RouterLink, useLocation, useNavigate } from "react-router-dom";
import { EmailIcon } from "@chakra-ui/icons";
import { FaSignInAlt } from "@shared/icons";
import { login } from "@api";
import { useAuth } from "@features/auth";
import { AuthFormCard, AuthInput, AuthPageHeader, AuthPageShell, PasswordInput } from "@features/auth";
import { AUTH_THEME, AUTH_PRIMARY_BUTTON_SX } from "@features/auth";
import { useMagnetic } from "@hooks/useMagnetic";
import { Reveal } from "@shared/motion/Reveal";
import { AUTH_LOGIN, AUTH_FIELDS } from "@/content/auth";
import extractErrorInfo from "@utils/errorHandler";
import VerifyCodeCard from "../components/VerifyCodeCard";
import FormErrorBanner from "../components/FormErrorBanner";

export default function LoginWidget() {
  const navigate = useNavigate();
  const location = useLocation();
  const { refreshSession, setAuthenticated } = useAuth();
  const magneticRef = useMagnetic(4);
  const emailRef = useRef(null);
  const errorRef = useRef(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [step, setStep] = useState("form"); // 'form' | 'verify'

  const from = location.state?.from?.pathname || "/chat";
  const emailInvalid = email.length > 0 && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

  // Autofocus первого поля при монтировании.
  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  // Перевод фокуса на алерт после неудачного сабмита (a11y).
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (isLoading) return;
    setError(null);
    if (emailInvalid) return;
    setIsLoading(true);
    try {
      // Пароль верный → бэкенд шлёт OTP на почту; сессия — только после verify.
      await login({ email, password });
      setStep("verify");
    } catch (err) {
      const { userMessage } = extractErrorInfo(err, { fallbackMessage: AUTH_LOGIN.errorFallback });
      setError(userMessage);
    } finally {
      setIsLoading(false);
    }
  };

  // OTP подтверждён (сессия-cookie уже выставлена бэкендом) → на исходный маршрут.
  const handleVerified = async () => {
    try {
      await refreshSession();
    } catch {
      setAuthenticated(true);
    }
    navigate(from, { replace: true });
  };

  if (step === "verify") {
    return (
      <VerifyCodeCard email={email} onVerified={handleVerified} onBack={() => setStep("form")} />
    );
  }

  return (
    <AuthPageShell>
      <AuthFormCard as="form" onSubmit={handleSubmit} maxW="100%">
        <Reveal as={VStack} variant="soft" className="stagger-children" w="full" align="stretch" spacing={5}>
          <AuthPageHeader title={AUTH_LOGIN.title} description={AUTH_LOGIN.description} />
          {error && (
            <FormErrorBanner ref={errorRef} title={AUTH_LOGIN.errorTitle} message={error} />
          )}
          <AuthInput inputRef={emailRef} id="email" label={AUTH_FIELDS.emailLabel} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={AUTH_FIELDS.emailPlaceholder} icon={EmailIcon} isRequired isInvalid={emailInvalid} errorMessage={AUTH_FIELDS.emailInvalid} autoComplete="email" />
          <PasswordInput id="password" label={AUTH_FIELDS.passwordLabel} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={AUTH_FIELDS.passwordPlaceholder} isRequired autoComplete="current-password" />
          <Button ref={magneticRef} type="submit" w="full" isLoading={isLoading} isDisabled={emailInvalid || !email || !password} leftIcon={<Icon as={FaSignInAlt} />} {...AUTH_PRIMARY_BUTTON_SX}>
            {isLoading ? AUTH_LOGIN.submitLoading : AUTH_LOGIN.submit}
          </Button>
          <Divider borderColor={AUTH_THEME.border} />
          <HStack spacing={1} justify="center" fontSize="sm">
            <Text color={AUTH_THEME.mutedText}>{AUTH_LOGIN.switchPrompt}</Text>
            <Link as={RouterLink} to="/register" color={AUTH_THEME.accent} fontWeight="500" _hover={{ color: AUTH_THEME.accentHover, textDecoration: "none" }}>
              {AUTH_LOGIN.switchAction}
            </Link>
          </HStack>
        </Reveal>
      </AuthFormCard>
    </AuthPageShell>
  );
}
