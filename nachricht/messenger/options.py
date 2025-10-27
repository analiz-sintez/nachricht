# from __future__ import annotations
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, get_type_hints

from ..bus import Signal, TerminalSignal, get_bus
from ..options import get_option_registry, OptionsMixin, Option, OptionGroup
from ..auth import User
from ..i18n import resolve
from .context import Context, Button, Keyboard


logger = logging.getLogger(__name__)


# #### UI Signals


@dataclass
class ShowOptionGroup(Signal):
    """Render and display an option group view."""

    obj_type: str
    obj_id: int
    path: str = ""


@dataclass
class ShowOption(Signal):
    """Render and display the detail view for a single option."""

    obj_type: str
    obj_id: int
    path: str


@dataclass
class SetOptionBool(Signal):
    """Set a boolean option to a specific value."""

    obj_type: str
    obj_id: int
    path: str
    value: bool


@dataclass
class SetOptionEnum(Signal):
    """Set an enum option to a specific value."""

    obj_type: str
    obj_id: int
    path: str
    value: str  # The string name of the enum member


@dataclass
class SetOptionFromReply(TerminalSignal):
    """
    Indicates the user's next text message should be the new value for an option.
    """

    obj_type: str
    obj_id: int
    path: str


# #### Helper Functions


async def _get_object(obj_type: str, obj_id: int) -> Optional[OptionsMixin]:
    """Retrieves a database object by its type name and ID."""
    if obj_type == "User":
        return User.query.get(obj_id)
    logger.error(f"Unknown object type for options UI: {obj_type}")
    return None


def _get_subgroup_info(
    path: str,
) -> dict[str, tuple[str, OptionGroup]]:
    """
    Gets the full path and class for all non-private subgroups of a given path.
    """
    registry = get_option_registry()
    subgroups = {}
    prefix = path + "/" if path else ""

    for p, option_cls in registry._paths.items():
        if not p.startswith(prefix):
            continue

        relative_path = p[len(prefix) :]
        if "/" not in relative_path:
            continue

        subgroup_name = relative_path.split("/")[0]
        full_subgroup_path = prefix + subgroup_name

        if full_subgroup_path not in subgroups:
            # Find the group class corresponding to this path
            group_cls = option_cls.group
            path_len = len(full_subgroup_path.split("/"))
            current_len = len(registry.get_path(option_cls).split("/")) - 1
            while current_len > path_len:
                group_cls = group_cls.group
                current_len -= 1

            if group_cls and not getattr(group_cls, "private", False):
                subgroups[full_subgroup_path] = (subgroup_name, group_cls)

    return subgroups


# #### UI Rendering


async def _render_options_view(ctx: Context, obj: OptionsMixin, path: str):
    """
    The main rendering function. It determines if the path is a group or an
    option and generates the appropriate text and keyboard.
    """
    registry = get_option_registry()
    option_cls = registry.get_option(path)
    buttons: list[list[Button]] = []
    text = ""
    on_reply_signal = None

    if option_cls is None:  # It's a group path
        # Get the group class to display its name
        group_name = "Options"
        if path:
            # Find any option within this path to get its group's name
            for p, opt_cls in registry._paths.items():
                if p.startswith(path):
                    parent_path = registry.get_parent_path(p)
                    if parent_path == path:
                        group_name = await resolve(
                            opt_cls.group.name, ctx.locale
                        )
                        break
        text = f"📁*{group_name}*"

        subgroups, child_options = registry.get_children(path)

        subgroup_buttons = [
            Button(
                text="📁" + await resolve(cls.name, ctx.locale),
                callback=ShowOptionGroup(
                    obj_type=obj.__class__.__name__, obj_id=obj.id, path=p
                ),
            )
            for p, cls in sorted(subgroups.items())
        ]
        buttons.extend([b] for b in subgroup_buttons)

        for opt in sorted(child_options, key=lambda o: o.name.msgid):
            opt_name = await resolve(opt.name, ctx.locale)
            if type(opt.value) is bool:
                opt_value = "✅ ON" if obj.option[opt] else "🚫 OFF"
            else:
                opt_value = str(obj.option[opt])
            button = Button(
                text=f"{opt_name}: {opt_value}",
                callback=ShowOption(
                    obj_type=obj.__class__.__name__,
                    obj_id=obj.id,
                    path=registry.get_path(opt),
                ),
            )
            buttons.append([button])

    else:  # It's an option path
        option_name = await resolve(option_cls.name, ctx.locale)
        option_desc = (
            await resolve(option_cls.description, ctx.locale)
            if option_cls.description
            else ""
        )
        current_value = obj.option[option_cls]
        text = f"*{option_name}*\n_{option_desc}_\n\nCurrent value: `{current_value}`"

        # Create editor buttons for bool/enum
        type_hints = get_type_hints(option_cls)
        value_type = type_hints.get("value")

        if value_type is bool:
            buttons.append(
                [
                    Button(
                        text="✅ On" if not current_value else "· ✅ On ·",
                        callback=SetOptionBool(
                            obj_type=obj.__class__.__name__,
                            obj_id=obj.id,
                            path=path,
                            value=True,
                        ),
                    ),
                    Button(
                        text="🚫 Off" if current_value else "· 🚫 Off ·",
                        callback=SetOptionBool(
                            obj_type=obj.__class__.__name__,
                            obj_id=obj.id,
                            path=path,
                            value=False,
                        ),
                    ),
                ]
            )
        elif isinstance(value_type, type) and issubclass(value_type, Enum):
            enum_buttons = [
                Button(
                    text=(
                        f"· {member.name} ·"
                        if member == current_value
                        else member.name
                    ),
                    callback=SetOptionEnum(
                        obj_type=obj.__class__.__name__,
                        obj_id=obj.id,
                        path=path,
                        value=member.name,
                    ),
                )
                for member in value_type
            ]
            buttons.append(enum_buttons)
        else:
            # For other types, set up reply-to-edit
            text += "\n\nReply to this message to set a new value."
            on_reply_signal = SetOptionFromReply(
                obj_type=obj.__class__.__name__, obj_id=obj.id, path=path
            )

    # Add "Back" button if not at the root
    parent_path = registry.get_parent_path(path)
    if parent_path is not None:
        buttons.append(
            [
                Button(
                    text="⬅️ Back",
                    callback=ShowOptionGroup(
                        obj_type=obj.__class__.__name__,
                        obj_id=obj.id,
                        path=parent_path,
                    ),
                )
            ]
        )

    await ctx.send_message(
        text=text, markup=Keyboard(buttons), on_reply=on_reply_signal
    )


# #### Signal Handlers


bus = get_bus()
if not bus:
    raise RuntimeError("Bus not initialized")
option_registry = get_option_registry()
if not option_registry:
    raise RuntimeError("OptionRegistry not initialized")


@bus.on(ShowOptionGroup)
@bus.on(ShowOption)
async def handle_show(ctx: Context, obj_type: str, obj_id: int, path: str):
    """Handles both ShowOptionGroup and ShowOption signals."""
    if option_registry.is_private(path):
        logger.warning(
            f"Attempt to access private option path by {obj_type} {obj_id}: {path}"
        )
        await ctx.send_message("This option cannot be viewed.")
        return
    obj = await _get_object(obj_type, obj_id)
    if obj:
        await _render_options_view(ctx, obj, path)


@bus.on(SetOptionBool)
async def handle_set_bool(
    ctx: Context, obj_type: str, obj_id: int, path: str, value: bool
):
    if option_registry.is_private(path):
        logger.warning(
            f"Attempt to edit private option by {obj_type} {obj_id}: {path}"
        )
        return
    obj = await _get_object(obj_type, obj_id)
    option_cls = option_registry.get_option(path)
    if obj and option_cls:
        try:
            obj.option[option_cls] = value
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to set option {path} for {obj}: {e}")
        await _render_options_view(ctx, obj, path)


@bus.on(SetOptionEnum)
async def handle_set_enum(
    ctx: Context, obj_type: str, obj_id: int, path: str, value: str
):
    if option_registry.is_private(path):
        logger.warning(
            f"Attempt to edit private option by {obj_type} {obj_id}: {path}"
        )
        return
    obj = await _get_object(obj_type, obj_id)
    option_cls = option_registry.get_option(path)
    if obj and option_cls:
        try:
            value_type = get_type_hints(option_cls).get("value")
            enum_member = value_type[value]
            obj.option[option_cls] = enum_member
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Failed to set option {path} for {obj}: {e}")
        await _render_options_view(ctx, obj, path)


@bus.on(SetOptionFromReply)
async def handle_set_from_reply(
    ctx: Context, obj_type: str, obj_id: int, path: str
):
    if option_registry.is_private(path):
        logger.warning(
            f"Attempt to edit private option by {obj_type} {obj_id}: {path}"
        )
        return
    obj = await _get_object(obj_type, obj_id)
    option_cls = option_registry.get_option(path)
    if not (obj and option_cls and ctx.message and ctx.message.text):
        return

    raw_value = ctx.message.text
    try:
        value_type = get_type_hints(option_cls).get("value")
        coerced_value = value_type(raw_value)
        obj.option[option_cls] = coerced_value
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Failed to coerce or set option value for {path} from '{raw_value}': {e}"
        )
        # Optionally send an error message to the user
    finally:
        # Re-render the view to show the new value or the old one if failed
        await _render_options_view(ctx, obj, path)
