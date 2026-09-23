import React, { useEffect, useMemo, useRef, useState } from "react";
import { Box, Button, Checkbox, Divider, HStack, Icon, Link, Text, VStack } from "@chakra-ui/react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { EmailIcon } from "@chakra-ui/icons";
import { FaUser, FaUserPlus } from "@shared/icons";
import { registerUser } from "@api";
import { AuthFormCard, AuthInput, AuthPageHeader, AuthPageShell, PasswordInput, PasswordStrength, useAuth } from "@features/auth";
import { AUTH_PRIMARY_BUTTON_SX } from "@features/auth";
import { colors } from "@theme/tokens";
import { AUTH_THEME } from "@features/auth";
import { useMagnetic } from "@hooks/useMagnetic";
import { Reveal } from "@shared/motion/Reveal";
import { AUTH_SIGNUP, AUTH_FIELDS } from "@/content/auth";
import extractErrorInfo from "@utils/errorHandler";
import VerifyCodeCard from "../components/VerifyCodeCard";
import FormErrorBanner from "../components/FormErrorBanner";

export default function SignupWidget() {
  const navigate = useNavigate();
  const magneticRef = useMagnetic(4);
  const { refreshSession, setAuthenticated } = useAuth();
  const emailRef = useRef(null);
  const errorRef = useRef(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [consentPd, setConsentPd] = useState(false);
  // Маркетинг — добровольно: регистрацию не блокирует.
  const [consentMarketing, setConsentMarketing] = useState(false);
  const [consentTransfer, setConsentTransfer] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [step, setStep] = useState("form"); // 'form' | 'verify'
  const emailInvalid = email.length > 0 && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  const emailDomain = useMemo(() => (email.includes("@") ? email.split("@")[1] : ""), [email]);
  const softEmailDomainWarning = useMemo(() => {
    if (!email || emailInvalid) return "";
    if (!emailDomain.includes(".")) return "Проверьте домен e-mail (отсутствует точка)";
    const suspiciousTlds = ["invalid", "example", "local", "test"];
    const tld = emailDomain.split(".").pop()?.toLowerCase();
    return tld && suspiciousTlds.includes(tld) ? "Похоже на тестовый домен — убедитесь, что он корректен" : "";
  }, [email, emailDomain, emailInvalid]);
  const hasMinLen = password.length >= 8;
  const hasLetter = /[A-Za-zА-Яа-я]/.test(password);
  const hasDigit = /\d/.test(password);
  const passwordsMismatch = password && confirmPassword && password !== confirmPassword;
  const passwordStrongEnough = hasMinLen && hasLetter && hasDigit;

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
    if (emailInvalid || !passwordStrongEnough || passwordsMismatch) return;
    if (!consentPd || !consentTransfer) return; // оба раздельных согласия обязательны
    setIsLoading(true);
    try {
      // Регистрация не логинит: бэкенд шлёт код на почту → переходим к вводу кода.
      await registerUser({
        email,
        password,
        first_name: firstName || null,
        consent_pd: consentPd,
        consent_transfer: consentTransfer,
        consent_marketing: consentMarketing,
        consent_version: AUTH_SIGNUP.consent.version,
      });
      setStep("verify");
    } catch (err) {
      const { userMessage } = extractErrorInfo(err, { fallbackMessage: AUTH_SIGNUP.errorFallback });
      setError(userMessage);
    } finally {
      setIsLoading(false);
    }
  };

  // Код подтверждён (сессия-cookie уже выставлена бэкендом) → в рабочее пространство.
  const handleVerified = async () => {
    try {
      await refreshSession();
    } catch {
      setAuthenticated(true);
    }
    navigate("/chat", { replace: true });
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
          <AuthPageHeader title={AUTH_SIGNUP.title} description={AUTH_SIGNUP.description} />
          {error && (
            <FormErrorBanner ref={errorRef} title={AUTH_SIGNUP.errorTitle} message={error} />
          )}
          <AuthInput inputRef={emailRef} id="email" label={AUTH_FIELDS.emailLabel} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={AUTH_FIELDS.emailPlaceholder} icon={EmailIcon} isRequired isInvalid={emailInvalid} errorMessage={AUTH_FIELDS.emailInvalid} helperText={!emailInvalid && softEmailDomainWarning ? softEmailDomainWarning : null} autoComplete="email" />
          <Box w="full">
            <PasswordInput id="password" label={AUTH_FIELDS.passwordLabel} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={AUTH_FIELDS.passwordCreatePlaceholder} isRequired autoComplete="new-password" />
            {password && <PasswordStrength password={password} />}
          </Box>
          <PasswordInput id="confirmPassword" label={AUTH_FIELDS.passwordConfirmLabel} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder={AUTH_FIELDS.passwordConfirmPlaceholder} isRequired isInvalid={passwordsMismatch} errorMessage={AUTH_FIELDS.passwordMismatch} autoComplete="new-password" />
          <Divider borderColor={AUTH_THEME.border} />
          <AuthInput id="firstName" label={AUTH_FIELDS.nameLabel} type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)} placeholder={AUTH_FIELDS.namePlaceholder} icon={FaUser} autoComplete="given-name" />
          <VStack align="stretch" spacing={2.5}>
            <Checkbox
              isChecked={consentPd}
              onChange={(e) => setConsentPd(e.target.checked)}
              colorScheme="blue"
              size="sm"
              alignItems="flex-start"
              sx={{ ".chakra-checkbox__control": { mt: "3px" } }}
            >
              <Text as="span" fontSize="11.5px" color={colors.fg[3]} lineHeight="1.55">
                {AUTH_SIGNUP.consent.pd.lead}{" "}
                <Link href="/legal/consent" isExternal onClick={(e) => e.stopPropagation()} color={AUTH_THEME.accent} textDecoration="underline" _hover={{ color: AUTH_THEME.accentHover }}>
                  {AUTH_SIGNUP.consent.pd.consentLink}
                </Link>{" "}
                {AUTH_SIGNUP.consent.pd.mid}{" "}
                <Link href="/legal/offer" isExternal onClick={(e) => e.stopPropagation()} color={AUTH_THEME.accent} textDecoration="underline" _hover={{ color: AUTH_THEME.accentHover }}>
                  {AUTH_SIGNUP.consent.pd.offerLink}
                </Link>{" "}
                {AUTH_SIGNUP.consent.pd.and}{" "}
                <Link href="/legal/privacy" isExternal onClick={(e) => e.stopPropagation()} color={AUTH_THEME.accent} textDecoration="underline" _hover={{ color: AUTH_THEME.accentHover }}>
                  {AUTH_SIGNUP.consent.pd.privacyLink}
                </Link>.
              </Text>
            </Checkbox>
            <Checkbox
              isChecked={consentTransfer}
              onChange={(e) => setConsentTransfer(e.target.checked)}
              colorScheme="blue"
              size="sm"
              alignItems="flex-start"
              sx={{ ".chakra-checkbox__control": { mt: "3px" } }}
            >
              <Text as="span" fontSize="11.5px" color={colors.fg[3]} lineHeight="1.55">
                {AUTH_SIGNUP.consent.transfer.lead}{" "}
                <Link href="/legal/consent" isExternal onClick={(e) => e.stopPropagation()} color={AUTH_THEME.accent} textDecoration="underline" _hover={{ color: AUTH_THEME.accentHover }}>
                  {AUTH_SIGNUP.consent.transfer.consentLink}
                </Link>{" "}
                {AUTH_SIGNUP.consent.transfer.tail}.
              </Text>
            </Checkbox>
            {/* Маркетинг — ДОБРОВОЛЬНАЯ галочка: по умолчанию снята и регистрацию НЕ
                блокирует (см. isDisabled кнопки). Обязательное «согласие» согласием не
                является. Письма о состоянии аккаунта приходят и без неё. */}
            <Checkbox
              isChecked={consentMarketing}
              onChange={(e) => setConsentMarketing(e.target.checked)}
              colorScheme="blue"
              size="sm"
              alignItems="flex-start"
              sx={{ ".chakra-checkbox__control": { mt: "3px" } }}
            >
              <Text as="span" fontSize="11.5px" color={colors.fg[4]} lineHeight="1.55">
                {AUTH_SIGNUP.consent.marketing.text}
              </Text>
            </Checkbox>
          </VStack>
          <Button ref={magneticRef} type="submit" w="full" isLoading={isLoading} isDisabled={emailInvalid || !passwordStrongEnough || passwordsMismatch || !email || !password || !confirmPassword || !consentPd || !consentTransfer} leftIcon={<Icon as={FaUserPlus} />} {...AUTH_PRIMARY_BUTTON_SX}>
            {isLoading ? AUTH_SIGNUP.submitLoading : AUTH_SIGNUP.submit}
          </Button>
          <Text fontSize="12px" color={colors.fg[4]} textAlign="center">
            {AUTH_SIGNUP.perkNote}
          </Text>
          <Divider borderColor={AUTH_THEME.border} />
          <HStack spacing={1} justify="center" fontSize="sm">
            <Text color={AUTH_THEME.mutedText}>{AUTH_SIGNUP.switchPrompt}</Text>
            <Link as={RouterLink} to="/login" color={AUTH_THEME.accent} fontWeight="500" _hover={{ color: AUTH_THEME.accentHover, textDecoration: "none" }}>
              {AUTH_SIGNUP.switchAction}
            </Link>
          </HStack>
        </Reveal>
      </AuthFormCard>
    </AuthPageShell>
  );
}
