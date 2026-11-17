export type Language = "en" | "ar";

export interface Copy {
  sources: string;
  send: string;
  toggleDocs: string;
  clear: string;
  closePanel: string;
  knowledgeBase: string;
  upload: string;
  uploading: string;
  uploadHint: string;
  indexing: string;
  duplicateFile: string;
  replaceFile: string;
  loading: string;
  emptyDocs: string;
  ready: string;
  failed: string;
  chunks: string;
  delete: string;
  page: string;
  pdfPage: string;
  pending: string;
  processing: string;
  llmButton: string;
  llmTitle: string;
  llmIntro: string;
  llmProvider: string;
  llmModel: string;
  llmKey: string;
  llmKeyPlaceholder: string;
  llmVerify: string;
  llmChecking: string;
  llmSave: string;
  llmForget: string;
  llmClose: string;
  llmVerified: string;
  llmStored: string;
  llmNoKey: string;
  llmModeUser: string;
  llmModeServer: string;
  llmModeOffline: string;
  llmModeKeyRequired: string;
  llmKeyNeeded: string;
  byokHint: string;
  llmWarning: string;
  llmKeyRequired: string;
  llmFeatureOff: string;
  toggleThemeDark: string;
  toggleThemeLight: string;
  authButton: string;
  authTitle: string;
  authSignedInAs: string;
  authSignIn: string;
  authCreate: string;
  authSignOut: string;
  authEmail: string;
  authPassword: string;
  authInvite: string;
  authDisplayName: string;
  authSignInAction: string;
  authCreateAction: string;
  authWorking: string;
  authRegistrationClosed: string;
  authClose: string;
  authRole: string;
  authError: string;
  authRequired: string;
  authSessionFailed: string;
  authEmployer: string;
  authMember: string;
  authEmployerHint: string;
  authMemberHint: string;
  authSignInHint: string;
  authWorkspace: string;
  authWorkspaceName: string;
  authNoWorkspace: string;
  authNotProvided: string;
  authNoInvite: string;
  authInviteCreated: string;
  authCreatedHint: string;
  authInviteLink: string;
  authCopyInvite: string;
  authCopyFailed: string;
  authCopied: string;
  authInviteUnavailable: string;
  authContinue: string;
  authEmployerAction: string;
  authMemberAction: string;
  // Naming aliases for the same workspace copy, kept for callers that use
  // "code/url/create" wording instead of "invite/link/employer".
  authInviteCode: string;
  authInviteUrl: string;
  authCopy: string;
  authWorkspaceCreated: string;
  authCreateWorkspace: string;
  authJoinWorkspace: string;
  // Legacy aliases: no guest UI remains, but archived panels still type-check.
  authGuest: string;
  authGuestNote: string;
  authDemoClosed: string;
  resetTitle: string;
  resetIntro: string;
  resetNewPassword: string;
  resetConfirm: string;
  resetSubmit: string;
  resetWorking: string;
  resetDone: string;
  resetDoneHint: string;
  resetBack: string;
  resetInvalidLink: string;
  resetMismatch: string;
  resetTooShort: string;
  readOnlyDocs: string;
  manageUsers: string;
  usersTitle: string;
  usersSearch: string;
  usersSearchPlaceholder: string;
  usersShowGuests: string;
  usersHideGuests: string;
  usersRole: string;
  usersStatus: string;
  usersActive: string;
  usersDisabled: string;
  usersGuest: string;
  usersEnable: string;
  usersDisable: string;
  usersResetPassword: string;
  usersDelete: string;
  usersSync: string;
  usersSyncDone: string;
  usersPage: string;
  usersOf: string;
  usersAccounts: string;
  usersCreated: string;
  usersActions: string;
  usersEmpty: string;
  usersCancel: string;
  usersPrevious: string;
  usersNext: string;
  usersLocalNote: string;
  usersConfirmDelete: string;
  usersConfirmReset: string;
  usersGuardSelf: string;
  usersGuardLastAdmin: string;
  usersGuardGuestOnly: string;
  usersError: string;
  usersRoleViewer: string;
  usersRoleUser: string;
  usersRoleAdmin: string;
  // Friendly, locally-authored messages shown instead of raw server errors.
  genericError: string;
  badRequest: string;
  notFound: string;
  conflict: string;
  fileTooLarge: string;
  rateLimited: string;
  serviceUnavailable: string;
  networkError: string;
  verificationFailed: string;
  processingFailed: string;
  authInvalidCredentials: string;
  authInvalidInput: string;
  authDenied: string;
  resetUnavailable: string;
  usersResetSent: string;
  // Bolt design refresh: shell, view headers and stat cards.
  navChat: string;
  navLibrary: string;
  navUsers: string;
  navSettings: string;
  navWorkspace: string;
  navSignOut: string;
  menuOpen: string;
  menuClose: string;
  viewChatTitle: string;
  viewChatSubtitle: string;
  viewLibraryTitle: string;
  viewLibrarySubtitle: string;
  viewUsersTitle: string;
  viewUsersSubtitle: string;
  viewSettingsTitle: string;
  viewSettingsSubtitle: string;
  statDocuments: string;
  columnName: string;
  statAdmins: string;
  statMembers: string;
  statGuests: string;
  searchDocuments: string;
  appearance: string;
  theme: string;
  themeLight: string;
  themeDark: string;
  language: string;
  adminBadge: string;
  /** @deprecated Kept as a type-compatible alias; never rendered as a badge. */
  guestBadge: string;
  newChat: string;
  heroEyebrow: string;
  heroTitle: string;
  heroBody: string;
  featureCited: string;
  featureRtl: string;
}

export const COPY: Record<Language, Copy> = {
  en: {
    sources: "Sources",
    send: "Send message",
    toggleDocs: "Toggle documents panel",
    clear: "Clear conversation",
    closePanel: "Close panel",
    knowledgeBase: "Knowledge base",
    upload: "Upload a document",
    uploading: "Uploading…",
    uploadHint: "PDF, DOCX, TXT, MD · max 50MB",
    indexing: "Parsing and indexing…",
    duplicateFile: "This file is already in the knowledge base.",
    replaceFile: "Replace the existing copy",
    loading: "Loading…",
    emptyDocs: "No documents yet. Upload one to start searching.",
    ready: "ready",
    failed: "failed",
    chunks: "chunks",
    delete: "Delete",
    page: "p.",
    pdfPage: "PDF page",
    pending: "pending",
    processing: "processing",
    llmButton: "Use your own LLM key",
    llmTitle: "Use your own LLM key",
    llmIntro:
      "Paste an OpenAI-compatible key to get real model answers. Without a key the built-in extractive answerer is used.",
    llmProvider: "Provider",
    llmModel: "Model",
    llmKey: "API key",
    llmKeyPlaceholder: "sk-…",
    llmVerify: "Verify key",
    llmChecking: "Checking…",
    llmSave: "Save & use",
    llmForget: "Forget key",
    llmClose: "Close",
    llmVerified: "The provider accepted this key.",
    llmStored: "Stored in this tab only",
    llmNoKey: "No key — using the built-in answerer",
    llmModeUser: "your key",
    llmModeServer: "server key",
    llmModeOffline: "offline",
    llmModeKeyRequired: "key required",
    llmKeyNeeded:
      "The server API key is reserved for administrators. Add your own provider key to ask questions.",
    byokHint:
      "This answer came from the built-in fallback and may be incomplete. Add your own LLM key for a fuller answer.",
    llmWarning:
      "The key is sent with each request to this app's server, used once, and never stored. It disappears when you close this tab.",
    llmKeyRequired: "Paste a key first.",
    llmFeatureOff: "Bring-your-own-key is disabled on this deployment.",
    toggleThemeDark: "Toggle dark theme",
    toggleThemeLight: "Toggle light theme",
    authButton: "Account",
    authTitle: "Account",
    authSignedInAs: "Signed in as",
    authSignIn: "Sign in",
    authCreate: "Create account",
    authSignOut: "Sign out",
    authEmail: "Email",
    authPassword: "Password",
    authInvite: "Invite code",
    authDisplayName: "Display name (optional)",
    authSignInAction: "Sign in",
    authCreateAction: "Create account",
    authWorking: "Working…",
    authRegistrationClosed:
      "Registration is closed on this deployment. Ask the operator for an invite.",
    authClose: "Close",
    authRole: "Role",
    authError: "Something went wrong. Try again.",
    authRequired:
      "You are not signed in, or your session has ended. Sign in, then try again.",
    authSessionFailed:
      "Sign-in succeeded, but this browser could not keep the session. Try again; if it persists, the deployment cannot verify session tokens.",
    authEmployer: "Employer",
    authMember: "Member",
    authEmployerHint: "Create a workspace and invite your team.",
    authMemberHint: "Join with the invite code from your employer.",
    authSignInHint: "Sign in with your workspace account.",
    authWorkspace: "Workspace",
    authWorkspaceName: "Workspace name",
    authNoWorkspace: "No workspace",
    authNotProvided: "Not provided",
    authNoInvite: "Ask your employer for an invite code.",
    authInviteCreated: "Workspace created",
    authCreatedHint: "Share this link with your team so they can join.",
    authInviteLink: "Invite link",
    authCopyInvite: "Copy invite link",
    authCopyFailed: "Could not copy the link. Select it and copy it manually.",
    authCopied: "Copied",
    authInviteUnavailable: "The invite code is unavailable. Sign in to see your workspace.",
    authContinue: "Continue to workspace",
    authEmployerAction: "Create workspace",
    authMemberAction: "Join workspace",
    authInviteCode: "Invite code",
    authInviteUrl: "Invite link",
    authCopy: "Copy invite link",
    authWorkspaceCreated: "Workspace created",
    authCreateWorkspace: "Create workspace",
    authJoinWorkspace: "Join workspace",
    // Legacy aliases with workspace wording; never shown by the new UI.
    authGuest: "Workspace member",
    authGuestNote: "Sign in with your workspace account to keep your chat history across visits.",
    authDemoClosed: "This option is unavailable. Sign in with your workspace account.",
    resetTitle: "Choose a new password",
    resetIntro:
      "Your reset link is single use. Enter a new password for this account; the old one stops working immediately.",
    resetNewPassword: "New password",
    resetConfirm: "Confirm new password",
    resetSubmit: "Set new password",
    resetWorking: "Saving…",
    resetDone: "Password updated",
    resetDoneHint: "You can now sign in with your new password.",
    resetBack: "Back to the app",
    resetInvalidLink:
      "This reset link is missing, invalid, or expired. Ask an administrator to send a new email.",
    resetMismatch: "The two passwords do not match.",
    resetTooShort: "Use at least {count} characters.",
    readOnlyDocs: "Sign in to upload documents. Deleting them is admin-only.",
    manageUsers: "Manage users",
    usersTitle: "User management",
    usersSearch: "Search",
    usersSearchPlaceholder: "Email or display name",
    usersShowGuests: "Show all accounts",
    usersHideGuests: "Hide all accounts",
    usersRole: "Role",
    usersStatus: "Status",
    usersActive: "Active",
    usersDisabled: "Disabled",
    usersGuest: "Member",
    usersEnable: "Enable",
    usersDisable: "Disable",
    usersResetPassword: "Reset password",
    usersDelete: "Delete",
    usersSync: "Sync from Supabase",
    usersSyncDone: "Synced {count} accounts",
    usersPage: "Page",
    usersOf: "of",
    usersAccounts: "accounts",
    usersCreated: "Created",
    usersActions: "Actions",
    usersEmpty: "No accounts match this search.",
    usersCancel: "Cancel",
    usersPrevious: "Previous page",
    usersNext: "Next page",
    usersLocalNote:
      "Local provider: password reset emails and Supabase sync are unavailable. Set SUPABASE_URL to enable them.",
    usersConfirmDelete: "Delete this account? This cannot be undone.",
    usersConfirmReset: "Send a password reset email to this account?",
    usersGuardSelf: "You cannot change your own role or status.",
    usersGuardLastAdmin: "At least one active admin must remain.",
    usersGuardGuestOnly: "Only accounts in this workspace can be deleted here.",
    usersError: "Failed to perform the action.",
    usersRoleViewer: "Viewer",
    usersRoleUser: "User",
    usersRoleAdmin: "Admin",
    genericError: "Something went wrong. Please try again.",
    badRequest: "The request could not be completed. Check your input and try again.",
    notFound: "The requested item was not found.",
    conflict: "This conflicts with existing data. Refresh and try again.",
    fileTooLarge: "The file is too large for this deployment.",
    rateLimited: "Too many requests. Wait a moment and try again.",
    serviceUnavailable: "The service is temporarily unavailable. Try again shortly.",
    networkError: "The service could not be reached. Check your connection and try again.",
    verificationFailed: "Could not verify the key. Check it and try again.",
    processingFailed: "The document could not be processed. Try another file or contact support.",
    authInvalidCredentials: "The email or password is incorrect.",
    authInvalidInput: "Check your details and try again.",
    authDenied: "This account action is not available. Check your invite or sign-in details.",
    resetUnavailable: "Password reset is not available on this deployment.",
    usersResetSent: "If the account exists, a reset email has been sent.",
    navChat: "Chat",
    navLibrary: "Library",
    navUsers: "Users",
    navSettings: "Settings",
    navWorkspace: "Workspace",
    navSignOut: "Sign out",
    menuOpen: "Open navigation",
    menuClose: "Close navigation",
    viewChatTitle: "Ask your documents",
    viewChatSubtitle: "Cited answers from your indexed knowledge base",
    viewLibraryTitle: "Document library",
    viewLibrarySubtitle: "Upload, index and manage the sources behind every answer",
    viewUsersTitle: "User management",
    viewUsersSubtitle: "Roles, access and workspace members",
    viewSettingsTitle: "Settings",
    viewSettingsSubtitle: "Appearance, privacy and your own provider key",
    statDocuments: "documents",
    columnName: "Name",
    statAdmins: "admins",
    statMembers: "members",
    statGuests: "members",
    searchDocuments: "Search documents…",
    appearance: "Appearance",
    theme: "Theme",
    themeLight: "Light",
    themeDark: "Dark",
    language: "Language",
    adminBadge: "Admin",
    guestBadge: "Member",
    newChat: "New chat",
    heroEyebrow: "EMPLOYEE AI SEARCH",
    heroTitle: "Your documents, answering in Arabic.",
    heroBody:
      "Upload a handbook, ask a question, and get an answer with the source right beside it. Indexing stays on your server; cited text reaches an LLM only when a key is used.",
    featureCited: "Answers with visible citations",
    featureRtl: "Arabic RTL, English too",
  },
  ar: {
    sources: "المصادر",
    send: "إرسال",
    toggleDocs: "إظهار أو إخفاء المستندات",
    clear: "مسح المحادثة",
    closePanel: "إغلاق اللوحة",
    knowledgeBase: "قاعدة المعرفة",
    upload: "ارفع مستنداً",
    uploading: "جارٍ الرفع",
    uploadHint: "PDF، DOCX، TXT، MD · الحد الأقصى 50 ميجابايت",
    indexing: "جارٍ التحليل والفهرسة…",
    duplicateFile: "هذا الملف موجود مسبقاً في قاعدة المعرفة.",
    replaceFile: "استبدال النسخة الحالية",
    loading: "جارٍ التحميل…",
    emptyDocs: "لا توجد مستندات بعد. ارفع مستنداً لبدء البحث.",
    ready: "جاهز",
    failed: "فشل",
    chunks: "مقطع",
    delete: "حذف",
    page: "ص",
    pdfPage: "صفحة الملف",
    pending: "قيد الانتظار",
    processing: "قيد المعالجة",
    llmButton: "استخدم مفتاح LLM الخاص بك",
    llmTitle: "استخدم مفتاح LLM الخاص بك",
    llmIntro:
      "الصق مفتاحاً متوافقاً مع OpenAI لتحصل على إجابات نموذج حقيقية. بدون مفتاح يُستخدم المُجيب الاستخلاصي المدمج.",
    llmProvider: "المزوّد",
    llmModel: "النموذج",
    llmKey: "مفتاح API",
    llmKeyPlaceholder: "sk-…",
    llmVerify: "تحقّق من المفتاح",
    llmChecking: "جارٍ التحقق…",
    llmSave: "حفظ واستخدام",
    llmForget: "انسَ المفتاح",
    llmClose: "إغلاق",
    llmVerified: "قبل المزوّد هذا المفتاح.",
    llmStored: "محفوظ في هذا التبويب فقط",
    llmNoKey: "لا يوجد مفتاح — يُستخدم المُجيب المدمج",
    llmModeUser: "مفتاحك",
    llmModeServer: "مفتاح الخادم",
    llmModeOffline: "بلا مفتاح",
    llmModeKeyRequired: "مفتاح مطلوب",
    llmKeyNeeded:
      "مفتاح الخادم مخصص للمدير فقط. أضف مفتاحك الخاص لطرح الأسئلة.",
    byokHint:
      "هذه الإجابة من المُجيب الاحتياطي المدمج وقد تكون غير كاملة. أضف مفتاح LLM خاصاً بك للحصول على إجابة أوضح.",
    llmWarning:
      "يُرسَل المفتاح مع كل طلب إلى خادم التطبيق، ويُستخدم مرة واحدة، ولا يُخزَّن. يختفي عند إغلاق هذا التبويب.",
    llmKeyRequired: "الصق المفتاح أولاً.",
    llmFeatureOff: "ميزة إحضار مفتاحك معطّلة على هذا النشر.",
    toggleThemeDark: "تبديل الوضع الداكن",
    toggleThemeLight: "تبديل الوضع الفاتح",
    authButton: "الحساب",
    authTitle: "الحساب",
    authSignedInAs: "مسجَّل الدخول باسم",
    authSignIn: "تسجيل الدخول",
    authCreate: "إنشاء حساب",
    authSignOut: "تسجيل الخروج",
    authEmail: "البريد الإلكتروني",
    authPassword: "كلمة المرور",
    authInvite: "رمز الدعوة",
    authDisplayName: "الاسم المعروض (اختياري)",
    authSignInAction: "دخول",
    authCreateAction: "إنشاء الحساب",
    authWorking: "جارٍ التنفيذ…",
    authRegistrationClosed:
      "التسجيل مغلق على هذا النشر. اطلب رمز دعوة من مشغّل النظام.",
    authClose: "إغلاق",
    authRole: "الدور",
    authError: "حدث خطأ. حاول مرة أخرى.",
    authRequired:
      "لم تسجّل الدخول أو انتهت جلستك. سجّل الدخول ثم أعد المحاولة.",
    authSessionFailed:
      "تم تسجيل الدخول، لكن المتصفح لم يحتفظ بالجلسة. أعد المحاولة، وإن استمرت المشكلة فالخادم لا يستطيع التحقق من رموز الجلسة.",
    authEmployer: "صاحب العمل",
    authMember: "عضو",
    authEmployerHint: "أنشئ مساحة عمل وادعُ فريقك للانضمام.",
    authMemberHint: "انضم برمز الدعوة الذي تحصل عليه من صاحب العمل.",
    authSignInHint: "سجّل الدخول بحسابك في مساحة العمل.",
    authWorkspace: "مساحة العمل",
    authWorkspaceName: "اسم مساحة العمل",
    authNoWorkspace: "لا توجد مساحة عمل",
    authNotProvided: "غير محدد",
    authNoInvite: "اطلب رمز الدعوة من صاحب العمل.",
    authInviteCreated: "تم إنشاء مساحة العمل",
    authCreatedHint: "شارك هذا الرابط مع فريقك لينضموا إليك.",
    authInviteLink: "رابط الدعوة",
    authCopyInvite: "نسخ رابط الدعوة",
    authCopyFailed: "تعذّر نسخ الرابط. حدّده ثم انسخه يدوياً.",
    authCopied: "تم النسخ",
    authInviteUnavailable: "رمز الدعوة غير متاح. سجّل الدخول لمشاهدة مساحة عملك.",
    authContinue: "المتابعة إلى مساحة العمل",
    authEmployerAction: "إنشاء مساحة العمل",
    authMemberAction: "الانضمام إلى مساحة العمل",
    authInviteCode: "رمز الدعوة",
    authInviteUrl: "رابط الدعوة",
    authCopy: "نسخ رابط الدعوة",
    authWorkspaceCreated: "تم إنشاء مساحة العمل",
    authCreateWorkspace: "إنشاء مساحة العمل",
    authJoinWorkspace: "الانضمام إلى مساحة العمل",
    // مرادفات قديمة بنصوص خالية من مفهوم الضيوف؛ لا تُعرض في الواجهة الجديدة.
    authGuest: "عضو في مساحة العمل",
    authGuestNote: "سجّل الدخول بحسابك في مساحة العمل للحفاظ على سجل محادثاتك بين الزيارات.",
    authDemoClosed: "هذا الخيار غير متاح. سجّل الدخول بحساب مساحة العمل.",
    resetTitle: "اختر كلمة مرور جديدة",
    resetIntro:
      "رابط إعادة التعيين يُستخدم مرة واحدة. أدخل كلمة مرور جديدة لهذا الحساب؛ تتوقف الكلمة القديمة عن العمل فوراً.",
    resetNewPassword: "كلمة المرور الجديدة",
    resetConfirm: "تأكيد كلمة المرور الجديدة",
    resetSubmit: "تعيين كلمة المرور",
    resetWorking: "جارٍ الحفظ…",
    resetDone: "تم تحديث كلمة المرور",
    resetDoneHint: "يمكنك الآن تسجيل الدخول بكلمة المرور الجديدة.",
    resetBack: "العودة إلى التطبيق",
    resetInvalidLink:
      "رابط إعادة التعيين مفقود أو غير صالح أو منتهي الصلاحية. اطلب من مشرف إرسال رسالة جديدة.",
    resetMismatch: "كلمتا المرور غير متطابقتين.",
    resetTooShort: "استخدم {count} أحرف على الأقل.",
    readOnlyDocs: "سجّل الدخول لرفع المستندات. الحذف متاح للمشرف فقط.",
    manageUsers: "إدارة المستخدمين",
    usersTitle: "إدارة المستخدمين",
    usersSearch: "بحث",
    usersSearchPlaceholder: "البريد الإلكتروني أو الاسم المعروض",
    usersShowGuests: "إظهار كل الحسابات",
    usersHideGuests: "إخفاء كل الحسابات",
    usersRole: "الدور",
    usersStatus: "الحالة",
    usersActive: "نشط",
    usersDisabled: "معطل",
    usersGuest: "عضو",
    usersEnable: "تفعيل",
    usersDisable: "تعطيل",
    usersResetPassword: "إعادة تعيين كلمة المرور",
    usersDelete: "حذف",
    usersSync: "مزامنة من Supabase",
    usersSyncDone: "تمت مزامنة {count} حساب",
    usersPage: "صفحة",
    usersOf: "من",
    usersAccounts: "حساب",
    usersCreated: "تاريخ الإنشاء",
    usersActions: "إجراءات",
    usersEmpty: "لا توجد حسابات مطابقة لهذا البحث.",
    usersCancel: "إلغاء",
    usersPrevious: "الصفحة السابقة",
    usersNext: "الصفحة التالية",
    usersLocalNote:
      "المزوّد المحلي: إعادة تعيين كلمة المرور والمزامنة مع Supabase غير متاحتين. عيّن SUPABASE_URL لتفعيلهما.",
    usersConfirmDelete: "حذف هذا الحساب؟ لا يمكن التراجع.",
    usersConfirmReset: "إرسال بريد لإعادة تعيين كلمة المرور لهذا الحساب؟",
    usersGuardSelf: "لا يمكنك تغيير دورك أو حالتك بنفسك.",
    usersGuardLastAdmin: "يجب أن يبقى مشرف نشط واحد على الأقل.",
    usersGuardGuestOnly: "لا يمكن حذف إلا الحسابات التابعة لهذه المساحة من هنا.",
    usersError: "فشل تنفيذ الإجراء.",
    usersRoleViewer: "مشاهد",
    usersRoleUser: "مستخدم",
    usersRoleAdmin: "مشرف",
    genericError: "حدث خطأ. حاول مرة أخرى.",
    badRequest: "تعذّر إكمال الطلب. تحقّق من الإدخال وحاول مرة أخرى.",
    notFound: "لم يتم العثور على العنصر المطلوب.",
    conflict: "يتعارض هذا الإجراء مع بيانات موجودة. حدّث الصفحة ثم أعد المحاولة.",
    fileTooLarge: "الملف أكبر من الحد المسموح على هذا النشر.",
    rateLimited: "طلبات كثيرة جداً. انتظر قليلاً ثم أعد المحاولة.",
    serviceUnavailable: "الخدمة غير متاحة مؤقتاً. حاول مرة أخرى بعد قليل.",
    networkError: "تعذّر الوصول إلى الخدمة. تحقّق من اتصالك ثم أعد المحاولة.",
    verificationFailed: "تعذّر التحقق من المفتاح. تحقّق منه ثم أعد المحاولة.",
    processingFailed: "تعذّت معالجة المستند. جرّب ملفاً آخر أو تواصل مع الدعم.",
    authInvalidCredentials: "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
    authInvalidInput: "تحقّق من بياناتك ثم أعد المحاولة.",
    authDenied: "هذا الإجراء غير متاح. تحقّق من رمز الدعوة أو بيانات الدخول.",
    resetUnavailable: "إعادة تعيين كلمة المرور غير متاحة على هذا النشر.",
    usersResetSent: "إذا كان الحساب موجوداً، فقد أُرسلت رسالة إعادة التعيين.",
    navChat: "المحادثة",
    navLibrary: "المكتبة",
    navUsers: "المستخدمون",
    navSettings: "الإعدادات",
    navWorkspace: "مساحة العمل",
    navSignOut: "تسجيل الخروج",
    menuOpen: "فتح القائمة",
    menuClose: "إغلاق القائمة",
    viewChatTitle: "اسأل مستنداتك",
    viewChatSubtitle: "إجابات موثّقة من قاعدة معارفك المفهرسة",
    viewLibraryTitle: "مكتبة المستندات",
    viewLibrarySubtitle: "ارفع المستندات وفهرسها وأدر المصادر التي تستند إليها الإجابات",
    viewUsersTitle: "إدارة المستخدمين",
    viewUsersSubtitle: "الأدوار والصلاحيات وأعضاء مساحة العمل",
    viewSettingsTitle: "الإعدادات",
    viewSettingsSubtitle: "المظهر والخصوصية ومفتاح مزوّدك الخاص",
    statDocuments: "مستند",
    columnName: "الاسم",
    statAdmins: "مديرون",
    statMembers: "أعضاء",
    statGuests: "أعضاء",
    searchDocuments: "ابحث في المستندات…",
    appearance: "المظهر",
    theme: "السمة",
    themeLight: "فاتح",
    themeDark: "داكن",
    language: "اللغة",
    adminBadge: "مدير",
    guestBadge: "عضو",
    newChat: "محادثة جديدة",
    heroEyebrow: "البحث الذكي في مستندات الموظفين",
    heroTitle: "مستنداتك تجيبك بالعربية.",
    heroBody:
      "ارفع دليل الموظفين، اسأل سؤالك، واحصل على إجابة مع مصدرها بجانبها. الفهرسة تبقى على خادمك، ولا يُرسل النص المسترجع إلى نموذج لغوي إلا عند استخدام مفتاح.",
    featureCited: "إجابات مع مصادر ظاهرة",
    featureRtl: "عربي RTL والإنجليزية أيضاً",
  },
};
