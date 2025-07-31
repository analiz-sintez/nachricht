# Nachricht: a Messenger Bots Framework

> Nachricht [German]: news; message; information.
> — Google Translate

## Overview

An abstraction layer for raw messenger libs like `python-telegram-bot`.

Messengers are wonderful media for small apps. They are inherently social which makes interactions easy. They are simple to use and develop for. And the are ubiquitous.

But while your project grows beyond a one-evening exercise, the problems emerge. To name the few:

* Code that uses a bot library quickly becomes a mess, because application-level primitives are missing: e.g. in python-telegram-bot, even flask-like routes are absent.
* The pieces of bot interface are not reusable: e.g. if you have a language selection menu as a command, you can't easily include it into the onboarding flow.
* As the bot grwos, monitoring and analytics tools become necessary. If you don't include them from the beginning, you'll face a huge refactoring.
* All the messengers offer mostly the same functions, so there's no need to write a bot for each messenger separately.

`nachricht` aims to address some of these challenges:

* It provides a messenger-agnostic interface to core messenger functions like sending messages, working with images, reactions etc.
* It defines convenient tools to define "endpoints" like commands, user messages, reactions.
* It employs a signal-slot paradigm which simplifies callbacks.
* It encourages you to describe user flows in terms of signals ans slots, and this sets you one step from user analytics and fine-grained reliability measurements.
* It includes useful batteries like authorization and internationalization so that you don't need to reinvent them by yourself.

## Examples

Define a command:
```python
@router.command("start", description="Start using the bot")
async def handle_start(ctx: Context):
    await ctx.send_message("Welcome to the Apex Bot!")
```

Handle user input:
```python
@router.message("(?P<text>.*)")
async def handle_input(ctx: Context, text: str):
    await ctx.send_message(f"You said: {text}.")
```

Define an inline keyboard:
```python
@dataclass
class PillSelected(Signal):
    pill: str

@router.command('start')
async def handle_start(ctx: Context):
    keyboard = Keyboard([[
		Button("Red pill", PillSelected("red")),
		Button("Blue pill", PillSelected("blue")),
		]])
    return await ctx.send_message("Take your choice.", keyboard)

@bus.on(PillSelected)
async def handle_pill(ctx: Context, pill: str):
    await ctx.send_message(f"So be it: {pill}")
```

For more examples and detailed explanations, see: ./docs/hacking.md.

## Development

The library is in an early stage of development. It is used to build Begriff language helper bot (from which it was fetched when its functions somewhat stabilized) and for some other small projects, so it is in a working condition, but:

* the completeness of the functions vary;
* the interfaces are not super convinient and due to change in future;
* the performance and stability is not well-measured.

It currently supports only Telegram, with Whatsapp and Matrix on the roadmap.

## Setup

Manually:
```
git clone https://github.com/analiz-sintez/nachricht.git
pip install -e nachricht/
```

From `requirements.txt`:
```
...
nachricht  @ git+https://github.com/analiz-sintez/nachricht.git
...
```

## Contribute

Bug reports and feature requests are very welcome.

If you decide to make a pull request, please make sure that the tests pass after your changes:

```
# Install or update the dependencies
make venv
# Run the tests
make test
```
