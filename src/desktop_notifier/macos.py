# -*- coding: utf-8 -*-
"""
UNUserNotificationCenter backend for macOS.

* Introduced in macOS 10.14.
* Cross-platform with iOS and iPadOS.
* Only available from signed app bundles if called from the main executable or from a
  signed Python framework (for example from python.org).
* Requires a running CFRunLoop to invoke callbacks.

"""

# system imports
import uuid
import logging
from concurrent.futures import Future
from typing import Optional, Callable, Any, cast

# external imports
from rubicon.objc import NSObject, ObjCClass, objc_method, py_from_ns  # type: ignore
from rubicon.objc.runtime import load_library, objc_id, objc_block  # type: ignore

# local imports
from .base import Notification, DesktopNotifierBase


__all__ = ["CocoaNotificationCenter"]

logger = logging.getLogger(__name__)

foundation = load_library("Foundation")
uns = load_library("UserNotifications")

UNUserNotificationCenter = ObjCClass("UNUserNotificationCenter")
UNMutableNotificationContent = ObjCClass("UNMutableNotificationContent")
UNNotificationRequest = ObjCClass("UNNotificationRequest")
UNNotificationAction = ObjCClass("UNNotificationAction")
UNTextInputNotificationAction = ObjCClass("UNTextInputNotificationAction")
UNNotificationCategory = ObjCClass("UNNotificationCategory")
UNNotificationSound = ObjCClass("UNNotificationSound")
UNNotificationAttachment = ObjCClass("UNNotificationAttachment")

NSURL = ObjCClass("NSURL")
NSSet = ObjCClass("NSSet")

UNNotificationDefaultActionIdentifier = (
    "com.apple.UNNotificationDefaultActionIdentifier"
)
UNNotificationDismissActionIdentifier = (
    "com.apple.UNNotificationDismissActionIdentifier"
)

UNAuthorizationOptionBadge = 1 << 0
UNAuthorizationOptionSound = 1 << 1
UNAuthorizationOptionAlert = 1 << 2

UNNotificationActionOptionAuthenticationRequired = 1 << 0
UNNotificationActionOptionDestructive = 1 << 1
UNNotificationActionOptionForeground = 1 << 2
UNNotificationActionOptionNone = 0

UNNotificationCategoryOptionNone = 0

UNAuthorizationStatusAuthorized = 2
UNAuthorizationStatusProvisional = 3
UNAuthorizationStatusEphemeral = 4


ReplyActionIdentifier = "com.desktop-notifier.ReplyActionIdentifier"


class NotificationCenterDelegate(NSObject):  # type: ignore
    """Delegate to handle user interactions with notifications"""

    @objc_method
    def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
        self, center, response, completion_handler: objc_block
    ) -> None:

        # Get the notification which was clicked from the platform ID.
        platform_nid = py_from_ns(response.notification.request.identifier)
        py_notification = self.interface._notification_for_nid[platform_nid]
        py_notification = cast(Notification, py_notification)

        # Invoke the callback which corresponds to the user interaction.
        if response.actionIdentifier == UNNotificationDefaultActionIdentifier:

            if py_notification.on_clicked:
                py_notification.on_clicked()

        elif response.actionIdentifier == UNNotificationDismissActionIdentifier:

            if py_notification.on_dismissed:
                py_notification.on_dismissed()

        elif response.actionIdentifier == ReplyActionIdentifier:

            if py_notification.on_replied:
                reply_text = py_from_ns(response.userText)
                py_notification.on_replied(reply_text)

        else:

            action_id_str = py_from_ns(response.actionIdentifier)
            callback = py_notification.buttons.get(action_id_str)

            if callback:
                callback()

        completion_handler()


class CocoaNotificationCenter(DesktopNotifierBase):
    """UNUserNotificationCenter backend for macOS

    Can be used with macOS Catalina and newer. Both app name and bundle identifier
    will be ignored. The notification center automatically uses the values provided
    by the app bundle.

    :param app_name: The name of the app. Does not have any effect because the app
        name is automatically determined from the bundle or framework.
    :param app_icon: The icon of the app. Does not have any effect because the app
        icon is automatically determined from the bundle or framework.
    :param notification_limit: Maximum number of notifications to keep in the system's
        notification center.
    """

    def __init__(
        self,
        app_name: str = "Python",
        app_icon: Optional[str] = None,
        notification_limit: Optional[int] = None,
    ) -> None:
        super().__init__(app_name, app_icon, notification_limit)
        self.nc = UNUserNotificationCenter.currentNotificationCenter()
        self.nc_delegate = NotificationCenterDelegate.alloc().init()
        self.nc_delegate.interface = self
        self.nc.delegate = self.nc_delegate

        self._clear_notification_categories()

    def request_authorisation(
        self, callback: Optional[Callable[[bool, str], Any]] = None
    ) -> None:
        """
        Request authorisation to send user notifications. This method returns
        immediately but authorisation will only be granted once the user has accepted
        the prompt. Use :attr:`has_authorisation` to check if we are authorised or pass
        a callback to be called when the request has been processed.

        :param callback: A method to call when the authorisation request has been
            granted or denied. The callback will be called with two arguments: a bool
            indicating if authorisation was granted and a string describing failure
            reasons for the request.
        """

        def on_auth_completed(granted: bool, error: objc_id) -> None:

            if callback:
                ns_error = py_from_ns(error)
                error_description = ns_error.localizedDescription if ns_error else ""
                callback(granted, error_description)

        self.nc.requestAuthorizationWithOptions(
            UNAuthorizationOptionAlert
            | UNAuthorizationOptionSound
            | UNAuthorizationOptionBadge,
            completionHandler=on_auth_completed,
        )

    @property
    def has_authorisation(self) -> bool:
        """Whether we have authorisation to send notifications."""

        # Get existing notification categories.

        future: Future = Future()

        def handler(settings: objc_id) -> None:
            settings = py_from_ns(settings)
            settings.retain()
            future.set_result(settings)

        self.nc.getNotificationSettingsWithCompletionHandler(handler)

        settings = future.result()

        authorized = settings.authorizationStatus in (
            UNAuthorizationStatusAuthorized,
            UNAuthorizationStatusProvisional,
            UNAuthorizationStatusEphemeral,
        )

        settings.release()

        return authorized

    def _send(
        self,
        notification: Notification,
        notification_to_replace: Optional[Notification],
    ) -> str:
        """
        Uses UNUserNotificationCenter to schedule a notification.

        :param notification: Notification to send.
        :param notification_to_replace: Notification to replace, if any.
        """

        if not self.has_authorisation:
            raise RuntimeError("Not authorised")

        if notification_to_replace:
            platform_nid = str(notification_to_replace.identifier)
        else:
            platform_nid = str(uuid.uuid4())

        # On macOS, we need need to register a new notification category for every
        # unique set of buttons.
        category_id = self._create_category_for_notification(notification)

        # Create the native notification + notification request.
        content = UNMutableNotificationContent.alloc().init()
        content.title = notification.title
        content.body = notification.message
        content.categoryIdentifier = category_id
        content.threadIdentifier = notification.thread

        if notification.sound:
            content.sound = UNNotificationSound.defaultSound

        if notification.attachment:
            url = NSURL.fileURLWithPath(notification.attachment)
            attachment = UNNotificationAttachment.attachmentWithIdentifier(
                "", URL=url, options={}, error=None
            )
            content.attachments = [attachment]

        notification_request = UNNotificationRequest.requestWithIdentifier(
            platform_nid, content=content, trigger=None
        )

        future: Future = Future()

        def handler(error: objc_id) -> None:
            ns_error = py_from_ns(error)
            error_description = ns_error.localizedDescription if ns_error else ""
            future.set_result(error_description)

        # Post the notification.
        self.nc.addNotificationRequest(
            notification_request, withCompletionHandler=handler
        )

        error = future.result()

        if error != "":
            raise RuntimeError(error)

        return platform_nid

    def _create_category_for_notification(
        self, notification: Notification
    ) -> Optional[str]:
        """
        Registers a new notification category with UNNotificationCenter for the given
        notification or retrieves an existing one if it exists for our set of buttons.

        :param notification: Notification instance.
        :returns: The identifier of the existing or created notification category.
        """

        if not (notification.buttons or notification.reply_field):
            return None

        button_titles = tuple(notification.buttons)
        ui_repr = f"buttons={button_titles}, reply_field={notification.reply_field}"
        category_id = f"desktop-notifier: {ui_repr}"

        # Retrieve existing categories. We do not cache this value because it may be
        # modified by other Python processes using desktop-notifier.

        categories = self._get_notification_categories()
        category_ids = set(py_from_ns(c.identifier) for c in categories.allObjects())  # type: ignore

        # Register new category if necessary.
        if category_id not in category_ids:

            # Create action for each button.
            actions = []

            if notification.reply_field:
                action = UNTextInputNotificationAction.actionWithIdentifier(
                    ReplyActionIdentifier,
                    title="Reply",
                    options=UNNotificationActionOptionNone,
                    textInputButtonTitle="Reply",
                    textInputPlaceholder="",
                )
                actions.append(action)

            for name in notification.buttons:
                action = UNNotificationAction.actionWithIdentifier(
                    name, title=name, options=UNNotificationActionOptionNone
                )
                actions.append(action)

            # Add category for new set of buttons.

            new_categories = categories.setByAddingObject(  # type: ignore
                UNNotificationCategory.categoryWithIdentifier(
                    category_id,
                    actions=actions,
                    intentIdentifiers=[],
                    options=UNNotificationCategoryOptionNone,
                )
            )
            self.nc.setNotificationCategories(new_categories)

        return category_id

    def _get_notification_categories(self) -> NSSet:  # type: ignore
        """Returns the registered notification categories for this app / Python."""

        future: Future = Future()

        def handler(categories: objc_id) -> None:
            categories = py_from_ns(categories)
            categories.retain()
            future.set_result(categories)

        self.nc.getNotificationCategoriesWithCompletionHandler(handler)

        categories = future.result()
        categories.autorelease()

        return categories

    def _clear_notification_categories(self) -> None:
        """Clears all registered notification categories for this application."""
        empty_set = NSSet.alloc().init()
        self.nc.setNotificationCategories(empty_set)

    def _clear(self, notification: Notification) -> None:
        """
        Removes a notifications from the notification center

        :param notification: Notification to clear.
        """
        self.nc.removeDeliveredNotificationsWithIdentifiers([notification.identifier])

    def _clear_all(self) -> None:
        """
        Clears all notifications from notification center

        The method executes asynchronously, returning immediately and removing the
        notifications on a background thread. This method does not affect any
        notification requests that are scheduled, but have not yet been delivered.
        """

        self.nc.removeAllDeliveredNotifications()
