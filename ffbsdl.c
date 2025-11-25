#include <stdio.h>
#include <stdint.h>
#include <limits.h>
#include <stdbool.h>
#include <string.h>
#include <stdlib.h>
#include <SDL2/SDL.h>
#include <SDL2/SDL_haptic.h>

typedef uint32_t effect_mask;

typedef enum {
	// top-level choices
	CREATE_EFFECT,
	MODIFY_EFFECT,
	PLAY_EFFECT,
	STOP_EFFECT,
	DESTROY_EFFECT,
	SET_AUTOCENTER,
	SET_GAIN,
	QUIT,

	// effect creation choices
	CREATE_CONSTANT,
	CREATE_SINE,
	CREATE_TRIANGLE,
	CREATE_SAWTOOTHUP,
	CREATE_SAWTOOTHDOWN,
	CREATE_RAMP,
	CREATE_SPRING,
	CREATE_DAMPER,
	CREATE_INERTIA,
	CREATE_FRICTION,

	// effect modification choices
	MODIFY_CONSTANT,
	MODIFY_SINE,
	MODIFY_TRIANGLE,
	MODIFY_SAWTOOTHUP,
	MODIFY_SAWTOOTHDOWN,
	MODIFY_RAMP,
	MODIFY_SPRING,
	MODIFY_DAMPER,
	MODIFY_INERTIA,
	MODIFY_FRICTION,

	TRY_AGAIN,
} choice;

typedef struct {
	effect_mask effect;
	char *option_str;
} effect_choice;

typedef struct {
	SDL_HapticEffect effect;
	int id;
	bool active;
} haptic_elem;

int init(){
	int ret = SDL_Init(SDL_INIT_HAPTIC);
	if(ret){
		puts(SDL_GetError());
		return ret;
	}

	return 0;
}

void cleanup(){
	SDL_Quit();
}

SDL_Haptic *get_haptic(){
	// open first haptic device, could be a good idea to try and let the
	// user choose which device to open but for now this is alright
	SDL_Haptic *haptic = SDL_HapticOpen(0);
	if(!haptic){
		fputs("Couldn't open haptic device.", stderr);
	} else {
		puts("Found haptic device:");
		puts(SDL_HapticName(0));
	}

	return haptic;
}

effect_mask get_supported_effects(SDL_Haptic *haptic){
	return SDL_HapticQuery(haptic);
}

void destroy_haptic(SDL_Haptic *haptic){
	SDL_HapticClose(haptic);
}

void destroy_joystick(SDL_Joystick *joy){
	SDL_JoystickClose(joy);
}

const char *get_haptic_type_name(uint16_t type){
#define CASE(x) case SDL_HAPTIC_##x: return #x

	switch(type){
		CASE(CONSTANT);
		CASE(SINE);
		CASE(TRIANGLE);
		CASE(SAWTOOTHUP);
		CASE(SAWTOOTHDOWN);
		CASE(RAMP);
		CASE(SPRING);
		CASE(DAMPER);
		CASE(FRICTION);
		CASE(INERTIA);
		CASE(CUSTOM);
	}

	return "ERR";

#undef CASE
}

void show_status(SDL_Haptic *haptic, size_t num_elems, haptic_elem elems[]){
	puts("EFFECTS:");
	puts("ID\tNAME\tSTATUS");

	for(size_t i = 0; i < num_elems; ++i){
		if(elems[i].active)
			printf("%i\t%s\t%s\n",
					elems[i].id,
					get_haptic_type_name(elems[i].effect.type),
					SDL_HapticGetEffectStatus(haptic, elems[i].id) ? "PLAYING" : "STOPPED"
			      );
	}

	puts("");
}

void show_choices(){
	puts("c: Create effect");
	puts("m: Modify effect");
	puts("p: Play effect");
	puts("s: Stop effect");
	puts("d: Destroy effect");
	puts("g: Set gain");
	puts("a: Set autocenter");
	puts("q: Quit");
}

void discard_line(){
	while(getchar() != '\n');
}

choice get_choice(){
	char c = getchar();
	discard_line();

	switch(c){
	case 'c': return CREATE_EFFECT;
	case 'm': return MODIFY_EFFECT;
	case 'p': return PLAY_EFFECT;
	case 's': return STOP_EFFECT;
	case 'd': return DESTROY_EFFECT;
	case 'a': return SET_AUTOCENTER;
	case 'g': return SET_GAIN;
	case 'q': return QUIT;
	}

	return TRY_AGAIN;
}

int get_int(const char *s, long long int min, long long int max, long long int d){
	// slightly dangerous, since someone could perform a buffer overflow
	// attack but I'll let it slide this once
	printf(s, min, max, d);

	int res;
	char in[80];
	fgets(in, sizeof(in), stdin);

	if(in[0] == '\n')
		res = d;
	else
		sscanf(in, "%i", &res);

	if(strlen(in) >= 79)
		discard_line();

	if(res < min)
		res = min;

	if(res > max)
		res = max;

	return res;
}

#define FFB_ATTR(n, x, a, b) \
	effect->n.x = get_int(#x " [%lli - %lli, current %lli]: ", a, b, effect->n.x)


#define CONSTANT_ATTR(x, a, b) \
	FFB_ATTR(constant, x, a, b)

#define SHORT_CONSTANT_ATTR(x) \
	CONSTANT_ATTR(x, SHRT_MIN, SHRT_MAX)

#define USHORT_CONSTANT_ATTR(x) \
	CONSTANT_ATTR(x, 0, USHRT_MAX)


#define PERIODIC_ATTR(x, a, b) \
	FFB_ATTR(periodic, x, a, b)

#define SHORT_PERIODIC_ATTR(x) \
	PERIODIC_ATTR(x, SHRT_MIN, SHRT_MAX)

#define USHORT_PERIODIC_ATTR(x) \
	PERIODIC_ATTR(x, 0, USHRT_MAX)


#define RAMP_ATTR(x, a, b) \
	FFB_ATTR(ramp, x, a, b)

#define SHORT_RAMP_ATTR(x) \
	RAMP_ATTR(x, 0, USHRT_MAX)


#define COND_ATTR(x, a, b) \
	FFB_ATTR(condition, x, a, b)

#define SHORT_COND_ATTR(x) \
	COND_ATTR(x, 0, USHRT_MAX)

void get_condition_effect_input(SDL_HapticEffect *effect){
	COND_ATTR(direction.dir[0], 0, 36000);
	COND_ATTR(length, 0, UINT_MAX);
	SHORT_COND_ATTR(delay);

	SHORT_COND_ATTR(right_sat[0]);
	SHORT_COND_ATTR(left_sat[0]);
	SHORT_COND_ATTR(right_coeff[0]);
	SHORT_COND_ATTR(left_coeff[0]);
	SHORT_COND_ATTR(deadband[0]);
	COND_ATTR(center[0], SHRT_MIN, SHRT_MAX);
}

void modify_inertia(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_condition_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_inertia(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_INERTIA;

	effect->condition.type = SDL_HAPTIC_INERTIA;

	effect->condition.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->condition.direction.dir[0] = 9000;
	effect->condition.length = 2000;
	effect->condition.delay = 0;

	effect->condition.right_sat[0] = 0;
	effect->condition.left_sat[0] = 0;
	effect->condition.right_coeff[0] = 0;
	effect->condition.left_coeff[0] = 0;
	effect->condition.deadband[0] = 0;
	effect->condition.center[0] = 0;

	get_condition_effect_input(effect);

#define SET(x) effect->condition.x

	SET(right_sat[2]) 	= SET(right_sat[1]) 	= SET(right_sat[0]);
	SET(left_sat[2]) 	= SET(left_sat[1]) 	= SET(left_sat[0]);
	SET(right_coeff[2]) 	= SET(right_coeff[1]) 	= SET(right_coeff[0]);
	SET(left_coeff[2]) 	= SET(left_coeff[1]) 	= SET(left_coeff[0]);
	SET(deadband[2]) 	= SET(deadband[1]) 	= SET(deadband[0]);
	SET(center[2]) 		= SET(center[1]) 	= SET(center[0]);

#undef SET

	return SDL_HapticNewEffect(haptic, effect);
}

void modify_friction(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_condition_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_friction(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_FRICTION;

	effect->condition.type = SDL_HAPTIC_FRICTION;

	effect->condition.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->condition.direction.dir[0] = 9000;
	effect->condition.length = 2000;
	effect->condition.delay = 0;

	effect->condition.right_sat[0] = 0;
	effect->condition.left_sat[0] = 0;
	effect->condition.right_coeff[0] = 0;
	effect->condition.left_coeff[0] = 0;
	effect->condition.deadband[0] = 0;
	effect->condition.center[0] = 0;

	get_condition_effect_input(effect);

#define SET(x) effect->condition.x

	SET(right_sat[2]) 	= SET(right_sat[1]) 	= SET(right_sat[0]);
	SET(left_sat[2]) 	= SET(left_sat[1]) 	= SET(left_sat[0]);
	SET(right_coeff[2]) 	= SET(right_coeff[1]) 	= SET(right_coeff[0]);
	SET(left_coeff[2]) 	= SET(left_coeff[1]) 	= SET(left_coeff[0]);
	SET(deadband[2]) 	= SET(deadband[1]) 	= SET(deadband[0]);
	SET(center[2]) 		= SET(center[1]) 	= SET(center[0]);

#undef SET

	return SDL_HapticNewEffect(haptic, effect);
}

void modify_damper(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_condition_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_damper(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_DAMPER;

	effect->condition.type = SDL_HAPTIC_DAMPER;

	effect->condition.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->condition.direction.dir[0] = 9000;
	effect->condition.length = 2000;
	effect->condition.delay = 0;

	effect->condition.right_sat[0] = 0;
	effect->condition.left_sat[0] = 0;
	effect->condition.right_coeff[0] = 0;
	effect->condition.left_coeff[0] = 0;
	effect->condition.deadband[0] = 0;
	effect->condition.center[0] = 0;

	get_condition_effect_input(effect);

#define SET(x) effect->condition.x

	SET(right_sat[2]) 	= SET(right_sat[1]) 	= SET(right_sat[0]);
	SET(left_sat[2]) 	= SET(left_sat[1]) 	= SET(left_sat[0]);
	SET(right_coeff[2]) 	= SET(right_coeff[1]) 	= SET(right_coeff[0]);
	SET(left_coeff[2]) 	= SET(left_coeff[1]) 	= SET(left_coeff[0]);
	SET(deadband[2]) 	= SET(deadband[1]) 	= SET(deadband[0]);
	SET(center[2]) 		= SET(center[1]) 	= SET(center[0]);

#undef SET

	return SDL_HapticNewEffect(haptic, effect);
}

void modify_spring(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_condition_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_spring(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_SPRING;

	effect->condition.type = SDL_HAPTIC_SPRING;

	effect->condition.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->condition.direction.dir[0] = 9000;
	effect->condition.length = 2000;
	effect->condition.delay = 0;

	effect->condition.right_sat[0] = 0;
	effect->condition.left_sat[0] = 0;
	effect->condition.right_coeff[0] = 0;
	effect->condition.left_coeff[0] = 0;
	effect->condition.deadband[0] = 0;
	effect->condition.center[0] = 0;

	get_condition_effect_input(effect);

#define SET(x) effect->condition.x

	SET(right_sat[2]) 	= SET(right_sat[1]) 	= SET(right_sat[0]);
	SET(left_sat[2]) 	= SET(left_sat[1]) 	= SET(left_sat[0]);
	SET(right_coeff[2]) 	= SET(right_coeff[1]) 	= SET(right_coeff[0]);
	SET(left_coeff[2]) 	= SET(left_coeff[1]) 	= SET(left_coeff[0]);
	SET(deadband[2]) 	= SET(deadband[1]) 	= SET(deadband[0]);
	SET(center[2]) 		= SET(center[1]) 	= SET(center[0]);

#undef SET

	return SDL_HapticNewEffect(haptic, effect);
}

void get_ramp_effect_input(SDL_HapticEffect *effect){
	RAMP_ATTR(direction.dir[0], 0, 36000);
	RAMP_ATTR(length, 0, UINT_MAX);
	SHORT_RAMP_ATTR(delay);

	SHORT_RAMP_ATTR(start);
	SHORT_RAMP_ATTR(end);

	SHORT_RAMP_ATTR(attack_length);
	SHORT_RAMP_ATTR(attack_level);
	SHORT_RAMP_ATTR(fade_length);
	SHORT_RAMP_ATTR(fade_level);
}

void modify_ramp(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_ramp_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_ramp(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_RAMP;
	effect->ramp.type = SDL_HAPTIC_TRIANGLE;

	effect->ramp.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->ramp.direction.dir[0] = 9000;
	effect->ramp.length = 2000;
	effect->ramp.delay = 0;

	effect->ramp.start = 0;
	effect->ramp.end = 65535;

	effect->ramp.attack_length = 0;
	effect->ramp.attack_level = 0;
	effect->ramp.fade_length = 0;
	effect->ramp.fade_level = 0;

	get_ramp_effect_input(effect);

	return SDL_HapticNewEffect(haptic, effect);
}

void get_periodic_effect_input(SDL_HapticEffect *effect){
	PERIODIC_ATTR(direction.dir[0], 0, 36000);
	PERIODIC_ATTR(length, 0, UINT_MAX);
	USHORT_PERIODIC_ATTR(delay);

	USHORT_PERIODIC_ATTR(period);
	SHORT_PERIODIC_ATTR(magnitude);
	SHORT_PERIODIC_ATTR(offset);
	USHORT_PERIODIC_ATTR(phase);

	SHORT_PERIODIC_ATTR(attack_length);
	SHORT_PERIODIC_ATTR(attack_level);
	SHORT_PERIODIC_ATTR(fade_length);
	SHORT_PERIODIC_ATTR(fade_level);
}

void modify_triangle(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_periodic_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_triangle(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_TRIANGLE;
	effect->periodic.type = SDL_HAPTIC_TRIANGLE;

	effect->periodic.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->periodic.direction.dir[0] = 9000;
	effect->periodic.length = 2000;
	effect->periodic.delay = 0;

	effect->periodic.period = 2000;
	effect->periodic.magnitude = 65535;
	effect->periodic.offset = 0;
	effect->periodic.phase = 0;

	effect->periodic.attack_length = 0;
	effect->periodic.attack_level = 0;
	effect->periodic.fade_length = 0;
	effect->periodic.fade_level = 0;

	get_periodic_effect_input(effect);

	return SDL_HapticNewEffect(haptic, effect);
}

void modify_sawtoothdown(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_periodic_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_sawtoothdown(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_SAWTOOTHDOWN;
	effect->periodic.type = SDL_HAPTIC_SAWTOOTHDOWN;

	effect->periodic.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->periodic.direction.dir[0] = 9000;
	effect->periodic.length = 2000;
	effect->periodic.delay = 0;

	effect->periodic.period = 2000;
	effect->periodic.magnitude = 65535;
	effect->periodic.offset = 0;
	effect->periodic.phase = 0;

	effect->periodic.attack_length = 0;
	effect->periodic.attack_level = 0;
	effect->periodic.fade_length = 0;
	effect->periodic.fade_level = 0;

	get_periodic_effect_input(effect);

	return SDL_HapticNewEffect(haptic, effect);
}

void modify_sawtoothup(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_periodic_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_sawtoothup(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_SAWTOOTHUP;
	effect->periodic.type = SDL_HAPTIC_SAWTOOTHUP;

	effect->periodic.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->periodic.direction.dir[0] = 9000;
	effect->periodic.length = 2000;
	effect->periodic.delay = 0;

	effect->periodic.period = 2000;
	effect->periodic.magnitude = 65535;
	effect->periodic.offset = 0;
	effect->periodic.phase = 0;

	effect->periodic.attack_length = 0;
	effect->periodic.attack_level = 0;
	effect->periodic.fade_length = 0;
	effect->periodic.fade_level = 0;

	get_periodic_effect_input(effect);

	return SDL_HapticNewEffect(haptic, effect);
}

void modify_sine(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_periodic_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_sine(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_SINE;
	effect->periodic.type = SDL_HAPTIC_SINE;

	effect->periodic.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->periodic.direction.dir[0] = 9000;
	effect->periodic.length = 2000;
	effect->periodic.delay = 0;

	effect->periodic.period = 2000;
	effect->periodic.magnitude = 65535;
	effect->periodic.offset = 0;
	effect->periodic.phase = 0;

	effect->periodic.attack_length = 0;
	effect->periodic.attack_level = 0;
	effect->periodic.fade_length = 0;
	effect->periodic.fade_level = 0;

	get_periodic_effect_input(effect);
	return SDL_HapticNewEffect(haptic, effect);
}

void get_constant_effect_input(SDL_HapticEffect *effect){
	CONSTANT_ATTR(direction.dir[0], 0, 36000);
	CONSTANT_ATTR(length, 0, UINT_MAX);
	USHORT_CONSTANT_ATTR(delay);

	SHORT_CONSTANT_ATTR(level);

	USHORT_CONSTANT_ATTR(attack_length);
	USHORT_CONSTANT_ATTR(attack_level);
	USHORT_CONSTANT_ATTR(fade_length);
	USHORT_CONSTANT_ATTR(fade_level);
}

void modify_constant(SDL_Haptic *haptic, int id, SDL_HapticEffect *effect){
	get_constant_effect_input(effect);
	SDL_HapticUpdateEffect(haptic, id, effect);
}

int create_constant(SDL_Haptic *haptic, SDL_HapticEffect *effect){
	effect->type = SDL_HAPTIC_CONSTANT;
	effect->constant.type = SDL_HAPTIC_CONSTANT;

	effect->constant.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->constant.direction.dir[0] = 9000;
	effect->constant.length = 2000;
	effect->constant.delay = 0;
	effect->constant.level = 32767;

	effect->constant.attack_length = 0;
	effect->constant.attack_level = 0;
	effect->constant.fade_length = 0;
	effect->constant.fade_level = 0;

	get_constant_effect_input(effect);

	return SDL_HapticNewEffect(haptic, effect);
}

void show_create_effect_choices(effect_mask supported_effects){
#define OPTION(x, c) {SDL_HAPTIC_##x, #c ": " #x}

	struct {
		uint16_t type;
		const char *option_str;
	} options[] = {
		OPTION(CONSTANT, c),
		OPTION(SINE, s),
		OPTION(TRIANGLE, t),
		OPTION(SAWTOOTHUP, u),
		OPTION(SAWTOOTHDOWN, d),
		OPTION(RAMP, r),
		OPTION(SPRING, S),
		OPTION(DAMPER, D),
		OPTION(INERTIA, i),
		OPTION(FRICTION, f),
	};

	for(size_t i = 0; i < sizeof(options) / sizeof(options[0]); ++i){
		if(options[i].type & supported_effects)
			puts(options[i].option_str);
	}

#undef OPTION
}

choice get_create_effect_choice(effect_mask supported_effects){
#define OPTION(x, c) {CREATE_##x, c}

	struct {
		choice x;
		char c;
	} options[] = {
		OPTION(CONSTANT, 'c'),
		OPTION(SINE, 's'),
		OPTION(TRIANGLE, 't'),
		OPTION(SAWTOOTHUP, 'u'),
		OPTION(SAWTOOTHDOWN, 'd'),
		OPTION(RAMP, 'r'),
		OPTION(SPRING, 'S'),
		OPTION(DAMPER, 'D'),
		OPTION(INERTIA, 'i'),
		OPTION(FRICTION, 'f'),
	};

	char option = 0;
	scanf("%c", &option);
	discard_line();

	for(size_t i = 0; i < sizeof(options) / sizeof(options[0]); ++i){
		if(options[i].c == option)
			return options[i].x;
	}

	return TRY_AGAIN;

#undef OPTION
}

void run_create_effect_choice(SDL_Haptic *haptic, size_t num_elems, haptic_elem elems[], choice c){
	haptic_elem *elem = 0;
	for(size_t i = 0; i < num_elems; ++i){
		if(!elems[i].active){
			elem = &elems[i];
			break;
		}
	}

	int id = 0;
	SDL_HapticEffect *effect = &elem->effect;

	switch(c){
	case CREATE_CONSTANT:
		id = create_constant(haptic, effect);
		break;

	case CREATE_SINE:
		id = create_sine(haptic, effect);
		break;

	case CREATE_TRIANGLE:
		id = create_triangle(haptic, effect);
		break;

	case CREATE_SAWTOOTHUP:
		id = create_sawtoothup(haptic, effect);
		break;

	case CREATE_SAWTOOTHDOWN:
		id = create_sawtoothdown(haptic, effect);
		break;

	case CREATE_RAMP:
		id = create_ramp(haptic, effect);
		break;

	case CREATE_SPRING:
		id = create_spring(haptic, effect);
		break;

	case CREATE_DAMPER:
		id = create_damper(haptic, effect);
		break;

	case CREATE_INERTIA:
		id = create_inertia(haptic, effect);
		break;

	case CREATE_FRICTION:
		id = create_friction(haptic, effect);
		break;
	}

	if(id < 0){
		fputs(SDL_GetError(), stderr);
		elem->active = false;
	} else {
		elem->id = id;
		elem->active = true;
	}
}

void create_effect(SDL_Haptic *haptic, size_t num_elems, haptic_elem elems[], effect_mask supported_effects){
	show_create_effect_choices(supported_effects);

	choice c;
	for(;;){
		c = get_create_effect_choice(supported_effects);

		if(c != TRY_AGAIN)
			break;
		else
			puts("Try again.");
	}

	run_create_effect_choice(haptic, num_elems, elems, c);
}

int get_id(size_t num_elems, haptic_elem elems[]){
	static int id = 0;
	id = get_int("Element ID [%i - %i, current %i]: ",
			0, num_elems, id);

	for(size_t i = 0; i < num_elems; ++i){
		if(elems[i].active && elems[i].id == id)
			return id;
	}

	fprintf(stderr, "Effect with ID %i not found.\n", id);

	return -1;
}

choice get_modify_choice(uint16_t t){
#define CHOICE(x) case SDL_HAPTIC_##x: return MODIFY_##x

	switch(t){
		CHOICE(CONSTANT);
		CHOICE(SINE);
		CHOICE(TRIANGLE);
		CHOICE(SAWTOOTHUP);
		CHOICE(SAWTOOTHDOWN);
		CHOICE(RAMP);
		CHOICE(SPRING);
		CHOICE(DAMPER);
		CHOICE(INERTIA);
		CHOICE(FRICTION);
	}

	return TRY_AGAIN;

#undef CHOICE
}

void modify_effect(SDL_Haptic *haptic, size_t num_elems, haptic_elem elems[]){
	haptic_elem *elem = 0;
	int id = get_id(num_elems, elems);

	if(id < 0)
		return;

	elem = &elems[id];

	SDL_HapticEffect *effect = &elem->effect;

	choice c = get_modify_choice(effect->type);
	switch(c){
	case MODIFY_CONSTANT:
		modify_constant(haptic, id, effect);
		break;

	case MODIFY_SINE:
		modify_sine(haptic, id, effect);
		break;

	case MODIFY_TRIANGLE:
		modify_triangle(haptic, id, effect);
		break;

	case MODIFY_SAWTOOTHUP:
		modify_sawtoothup(haptic, id, effect);
		break;

	case MODIFY_SAWTOOTHDOWN:
		modify_sawtoothdown(haptic, id, effect);
		break;

	case MODIFY_RAMP:
		modify_ramp(haptic, id, effect);
		break;

	case MODIFY_SPRING:
		modify_spring(haptic, id, effect);
		break;

	case MODIFY_DAMPER:
		modify_damper(haptic, id, effect);
		break;

	case MODIFY_INERTIA:
		modify_inertia(haptic, id, effect);
		break;

	case MODIFY_FRICTION:
		modify_friction(haptic, id, effect);
		break;
	}
}

void play_effect(SDL_Haptic *haptic, size_t num_elems, haptic_elem elems[]){
	int id = get_id(num_elems, elems);

	if(id < 0)
		return;

	static uint32_t iterations = 0;
	iterations = get_int("Iterations [%lli - %lli, current %lli]: ",
			0, UINT_MAX, iterations);

	SDL_HapticRunEffect(haptic, id, iterations);
}

void stop_effect(SDL_Haptic *haptic, size_t num_elems, haptic_elem elems[]){
	int id = get_id(num_elems, elems);

	if(id < 0)
		return;

	SDL_HapticStopEffect(haptic, id);
}

void destroy_effect(SDL_Haptic *haptic, size_t num_elems, haptic_elem elems[]){
	int id = get_id(num_elems, elems);

	if(id < 0)
		return;

	SDL_HapticDestroyEffect(haptic, id);
	elems[id].active = false;
}

void set_autocenter(SDL_Haptic *haptic){
	static int autocenter = 0;
	autocenter = get_int("Autocenter [%i - %i, current %i]: ",
			0, 100, autocenter);

	SDL_HapticSetAutocenter(haptic, autocenter);
}

void set_gain(SDL_Haptic *haptic){
	static int gain = 100;
	gain = get_int("Gain [%i - %i, current %i]: ",
			0, 100, gain);

	SDL_HapticSetGain(haptic, gain);
}

void run_choice(SDL_Haptic *haptic, size_t num_elems, haptic_elem elems[], effect_mask supported_effects, choice c){
	switch(c){
	case CREATE_EFFECT:
		create_effect(haptic, num_elems, elems, supported_effects);
		break;

	case MODIFY_EFFECT:
		modify_effect(haptic, num_elems, elems);
		break;

	case PLAY_EFFECT:
		play_effect(haptic, num_elems, elems);
		break;

	case STOP_EFFECT:
		stop_effect(haptic, num_elems, elems);
		break;

	case DESTROY_EFFECT:
		destroy_effect(haptic, num_elems, elems);
		break;

	case SET_AUTOCENTER:
		set_autocenter(haptic);
		break;

	case SET_GAIN:
		set_gain(haptic);
		break;
	}
}

void run(SDL_Haptic *haptic, effect_mask supported_effects){
	bool should_run = true;
	int num_elems = SDL_HapticNumEffects(haptic);

	haptic_elem *elems = (haptic_elem*)calloc(sizeof(haptic_elem), num_elems);
	do {
		show_status(haptic, num_elems, elems);

		show_choices();

		choice c;
		for(;;){
			c = get_choice();

			if(c != TRY_AGAIN)
				break;
			else
				puts("Try again.");
		}

		if(c == QUIT)
			should_run = false;
		else
			run_choice(haptic, num_elems, elems, supported_effects, c);

	} while(should_run);

	free(elems);
}


typedef struct {
	int noninteractive;
	int show_help;
	const char *effect_type_str;
	uint16_t effect_type;
	int direction_deg;
	uint32_t length_ms;
	uint32_t delay_ms;
	int iterations;
	int gain;
	int level;
	int magnitude;
	uint32_t period_ms;
	int offset;
	int phase_deg;
	uint32_t attack_length_ms;
	int attack_level;
	uint32_t fade_length_ms;
	int fade_level;
	int ramp_start;
	int ramp_end;
	int cond_right_sat;
	int cond_left_sat;
	int cond_right_coeff;
	int cond_left_coeff;
	int cond_deadband;
	int cond_center;
} EffectArgs;

static void init_effect_args(EffectArgs *a){
	memset(a, 0, sizeof(*a));
	a->direction_deg = -1;
	a->iterations = 1;
	a->gain = -1;
	a->level = INT_MIN;
	a->magnitude = INT_MIN;
	a->ramp_start = INT_MIN;
	a->ramp_end = INT_MIN;
	a->cond_right_sat = INT_MIN;
	a->cond_left_sat = INT_MIN;
	a->cond_right_coeff = INT_MIN;
	a->cond_left_coeff = INT_MIN;
	a->cond_deadband = INT_MIN;
	a->cond_center = INT_MIN;
}

static uint16_t parse_effect_type(const char *s){
	if(!s) return 0;
	if(strcmp(s, "constant") == 0) return SDL_HAPTIC_CONSTANT;
	if(strcmp(s, "sine") == 0) return SDL_HAPTIC_SINE;
	if(strcmp(s, "triangle") == 0) return SDL_HAPTIC_TRIANGLE;
	if(strcmp(s, "sawtoothup") == 0) return SDL_HAPTIC_SAWTOOTHUP;
	if(strcmp(s, "sawtoothdown") == 0) return SDL_HAPTIC_SAWTOOTHDOWN;
	if(strcmp(s, "ramp") == 0) return SDL_HAPTIC_RAMP;
	if(strcmp(s, "spring") == 0) return SDL_HAPTIC_SPRING;
	if(strcmp(s, "damper") == 0) return SDL_HAPTIC_DAMPER;
	if(strcmp(s, "inertia") == 0) return SDL_HAPTIC_INERTIA;
	if(strcmp(s, "friction") == 0) return SDL_HAPTIC_FRICTION;
	return 0;
}

static void parse_effect_args(int argc, char **argv, EffectArgs *out){
	init_effect_args(out);
	for(int i = 1; i < argc; ++i){
		if(strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0 ||
		   strcmp(argv[i], "--help-batch") == 0){
			out->show_help = 1;
			return;
		} else if(strcmp(argv[i], "--effect-type") == 0 && i + 1 < argc){
			out->effect_type_str = argv[++i];
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--direction-deg") == 0 && i + 1 < argc){
			out->direction_deg = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--length-ms") == 0 && i + 1 < argc){
			out->length_ms = (uint32_t)atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--delay-ms") == 0 && i + 1 < argc){
			out->delay_ms = (uint32_t)atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--level") == 0 && i + 1 < argc){
			out->level = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--magnitude") == 0 && i + 1 < argc){
			out->magnitude = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--period-ms") == 0 && i + 1 < argc){
			out->period_ms = (uint32_t)atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--offset") == 0 && i + 1 < argc){
			out->offset = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--phase-deg") == 0 && i + 1 < argc){
			out->phase_deg = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--attack-length-ms") == 0 && i + 1 < argc){
			out->attack_length_ms = (uint32_t)atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--attack-level") == 0 && i + 1 < argc){
			out->attack_level = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--fade-length-ms") == 0 && i + 1 < argc){
			out->fade_length_ms = (uint32_t)atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--fade-level") == 0 && i + 1 < argc){
			out->fade_level = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--iterations") == 0 && i + 1 < argc){
			out->iterations = atoi(argv[++i]);
			if(out->iterations <= 0)
				out->iterations = 1;
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--ramp-start") == 0 && i + 1 < argc){
			out->ramp_start = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--ramp-end") == 0 && i + 1 < argc){
			out->ramp_end = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--cond-right-sat") == 0 && i + 1 < argc){
			out->cond_right_sat = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--cond-left-sat") == 0 && i + 1 < argc){
			out->cond_left_sat = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--cond-right-coeff") == 0 && i + 1 < argc){
			out->cond_right_coeff = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--cond-left-coeff") == 0 && i + 1 < argc){
			out->cond_left_coeff = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--cond-deadband") == 0 && i + 1 < argc){
			out->cond_deadband = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--cond-center") == 0 && i + 1 < argc){
			out->cond_center = atoi(argv[++i]);
			out->noninteractive = 1;
		} else if(strcmp(argv[i], "--gain") == 0 && i + 1 < argc){
			out->gain = atoi(argv[++i]);
			out->noninteractive = 1;
		}
	}
	out->effect_type = parse_effect_type(out->effect_type_str);
}

static uint16_t deg_to_sdl_dir(int deg){
	if(deg < 0)
		return 9000;
	if(deg > 360)
		deg = 360;
	return (uint16_t)(deg * 100);
}

static void setup_constant_from_args(SDL_HapticEffect *effect, const EffectArgs *a){
	memset(effect, 0, sizeof(*effect));
	effect->type = SDL_HAPTIC_CONSTANT;
	effect->constant.type = SDL_HAPTIC_CONSTANT;
	effect->constant.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->constant.direction.dir[0] = deg_to_sdl_dir(a->direction_deg);
	effect->constant.length = a->length_ms ? a->length_ms : 2000;
	effect->constant.delay = a->delay_ms;
	effect->constant.level = (a->level != INT_MIN) ? a->level : 32767;
	effect->constant.attack_length = a->attack_length_ms;
	effect->constant.attack_level = a->attack_level;
	effect->constant.fade_length = a->fade_length_ms;
	effect->constant.fade_level = a->fade_level;
}

static void setup_periodic_from_args(SDL_HapticEffect *effect, uint16_t type, const EffectArgs *a){
	memset(effect, 0, sizeof(*effect));
	effect->type = type;
	effect->periodic.type = type;
	effect->periodic.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->periodic.direction.dir[0] = deg_to_sdl_dir(a->direction_deg);
	effect->periodic.length = a->length_ms ? a->length_ms : 2000;
	effect->periodic.delay = a->delay_ms;
	effect->periodic.period = a->period_ms ? a->period_ms : 2000;
	effect->periodic.magnitude = (a->magnitude != INT_MIN) ? a->magnitude : 32767;
	effect->periodic.offset = a->offset;
	effect->periodic.phase = (uint16_t)(a->phase_deg * 100);
	effect->periodic.attack_length = a->attack_length_ms;
	effect->periodic.attack_level = a->attack_level;
	effect->periodic.fade_length = a->fade_length_ms;
	effect->periodic.fade_level = a->fade_level;
}

static void setup_ramp_from_args(SDL_HapticEffect *effect, const EffectArgs *a){
	memset(effect, 0, sizeof(*effect));
	effect->type = SDL_HAPTIC_RAMP;
	effect->ramp.type = SDL_HAPTIC_TRIANGLE;
	effect->ramp.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->ramp.direction.dir[0] = deg_to_sdl_dir(a->direction_deg);
	effect->ramp.length = a->length_ms ? a->length_ms : 2000;
	effect->ramp.delay = a->delay_ms;
	effect->ramp.start = (a->ramp_start != INT_MIN) ? a->ramp_start : 0;
	effect->ramp.end = (a->ramp_end != INT_MIN) ? a->ramp_end : 65535;
	effect->ramp.attack_length = a->attack_length_ms;
	effect->ramp.attack_level = a->attack_level;
	effect->ramp.fade_length = a->fade_length_ms;
	effect->ramp.fade_level = a->fade_level;
}

static void setup_condition_from_args(SDL_HapticEffect *effect, uint16_t type, const EffectArgs *a){
	memset(effect, 0, sizeof(*effect));
	effect->type = type;
	effect->condition.type = type;
	effect->condition.direction.type = SDL_HAPTIC_CARTESIAN;
	effect->condition.direction.dir[0] = deg_to_sdl_dir(a->direction_deg);
	effect->condition.length = a->length_ms ? a->length_ms : 2000;
	effect->condition.delay = a->delay_ms;
	if(a->cond_right_sat != INT_MIN)
		effect->condition.right_sat[0] = a->cond_right_sat;
	if(a->cond_left_sat != INT_MIN)
		effect->condition.left_sat[0] = a->cond_left_sat;
	if(a->cond_right_coeff != INT_MIN)
		effect->condition.right_coeff[0] = a->cond_right_coeff;
	if(a->cond_left_coeff != INT_MIN)
		effect->condition.left_coeff[0] = a->cond_left_coeff;
	if(a->cond_deadband != INT_MIN)
		effect->condition.deadband[0] = a->cond_deadband;
	if(a->cond_center != INT_MIN)
		effect->condition.center[0] = a->cond_center;
#define SET(x) effect->condition.x
	SET(right_sat[2]) = SET(right_sat[1]) = SET(right_sat[0]);
	SET(left_sat[2])  = SET(left_sat[1])  = SET(left_sat[0]);
	SET(right_coeff[2]) = SET(right_coeff[1]) = SET(right_coeff[0]);
	SET(left_coeff[2])  = SET(left_coeff[1])  = SET(left_coeff[0]);
	SET(deadband[2])    = SET(deadband[1])    = SET(deadband[0]);
	SET(center[2])      = SET(center[1])      = SET(center[0]);
#undef SET
}


static int run_single_effect_from_args(SDL_Haptic *haptic, effect_mask supported_effects, const EffectArgs *a){
	if(!a->effect_type_str || !a->effect_type){
		fprintf(stderr, "Invalid or missing --effect-type for non-interactive mode. Use --help for usage.\n");
		return -1;
	}

	if(!(supported_effects & a->effect_type)){
		fprintf(stderr, "Requested effect type not supported by this device.\n");
		return -1;
	}

	/* Apply optional global gain if provided in batch mode.
	 * This is analogous to the interactive set_gain() helper but
	 * controlled entirely via CLI (e.g. --gain 5 for 5%%).
	 *
	 * The gain value can be specified either as:
	 *   - a percentage in the range [0, 100], or
	 *   - a 16-bit value in the range [0, 65535], which is scaled to [0, 100].
	 */
	if(a->gain >= 0){
		int gain_pct;
		if(a->gain <= 100){
			gain_pct = a->gain;
		} else if(a->gain <= 65535){
			/* Scale 0..65535 into 0..100 with rounding. */
			gain_pct = (int)((a->gain * 100 + 32767) / 65535);
		} else {
			gain_pct = 100;
		}

		if(gain_pct < 0)
			gain_pct = 0;
		else if(gain_pct > 100)
			gain_pct = 100;

		SDL_HapticSetGain(haptic, gain_pct);
	}

	SDL_HapticEffect effect;
	if(a->effect_type == SDL_HAPTIC_CONSTANT){
		setup_constant_from_args(&effect, a);
	} else if(a->effect_type == SDL_HAPTIC_SINE ||
	          a->effect_type == SDL_HAPTIC_TRIANGLE ||
	          a->effect_type == SDL_HAPTIC_SAWTOOTHUP ||
	          a->effect_type == SDL_HAPTIC_SAWTOOTHDOWN){
		setup_periodic_from_args(&effect, a->effect_type, a);
	} else if(a->effect_type == SDL_HAPTIC_RAMP){
		setup_ramp_from_args(&effect, a);
	} else if(a->effect_type == SDL_HAPTIC_SPRING ||
	          a->effect_type == SDL_HAPTIC_DAMPER ||
	          a->effect_type == SDL_HAPTIC_INERTIA ||
	          a->effect_type == SDL_HAPTIC_FRICTION){
		setup_condition_from_args(&effect, a->effect_type, a);

	} else {
		fprintf(stderr, "Batch mode does not support the requested effect type.\n");
		return -1;
	}

	int id = SDL_HapticNewEffect(haptic, &effect);
	if(id < 0){
		fputs(SDL_GetError(), stderr);
		fputc('\n', stderr);
		return -1;
	}

	SDL_HapticRunEffect(haptic, id, a->iterations);
	Uint32 duration = a->length_ms ? a->length_ms : 2000;
	duration *= (Uint32)a->iterations;
	duration += a->delay_ms;
	SDL_Delay(duration + 100);

	SDL_HapticDestroyEffect(haptic, id);
	return 0;
}

static void print_batch_usage(const char *progname)
{
	printf("Usage: %s [--effect-type TYPE] [options...]\n\n", progname);
	puts("No arguments: start interactive menu mode.");
	puts("Non-interactive (batch) mode is selected when you pass --effect-type or any effect parameters.\n");

	puts("Effect types:");
	puts("  --effect-type constant        Constant force effect");
	puts("  --effect-type sine            Periodic sine effect");
	puts("  --effect-type triangle        Periodic triangle effect");
	puts("  --effect-type sawtoothup      Periodic sawtooth-up effect");
	puts("  --effect-type sawtoothdown    Periodic sawtooth-down effect");
	puts("  --effect-type ramp            Ramp effect (start -> end)");
	puts("  --effect-type spring          Condition effect (spring)");
	puts("  --effect-type damper          Condition effect (damper)");
	puts("  --effect-type inertia         Condition effect (inertia)");
	puts("  --effect-type friction        Condition effect (friction)\n");

	puts("Common parameters:");
	puts("  --direction-deg <0-360>       Direction in degrees (0, 90, 180, 270, ...)");
	puts("  --length-ms <ms>              Effect length in milliseconds");
	puts("  --delay-ms <ms>               Delay before effect starts (ms)");
	puts("  --iterations <n>              Number of times to play the effect");
	puts("  --gain <0-100>                Global force feedback gain percentage");
	puts("  --attack-length-ms <ms>       Envelope attack length in ms");
	puts("  --attack-level <val>         Envelope attack level");
	puts("  --fade-length-ms <ms>         Envelope fade length in ms");
	puts("  --fade-level <val>           Envelope fade level\n");

	puts("Constant force parameters:");
	puts("  --level <val>                 Constant force level (int16)");
	puts("Periodic parameters (sine/triangle/sawtoothup/sawtoothdown):");
	puts("  --magnitude <val>             Wave magnitude (int16)");
	puts("  --period-ms <ms>              Wave period in ms (e.g. 10, 100, 1000)");
	puts("  --phase-deg <0-360>           Wave phase in degrees");
	puts("  --offset <val>                Wave offset (int16)\n");

	puts("Ramp parameters:");
	puts("  --ramp-start <val>            Ramp start level (int16)");
	puts("  --ramp-end <val>              Ramp end level (int16)\n");

	puts("Condition parameters (spring/damper/inertia/friction):");
	puts("  --cond-right-sat <val>        Right saturation (int16)");
	puts("  --cond-left-sat <val>         Left saturation (int16)");
	puts("  --cond-right-coeff <val>      Right coefficient (int16)");
	puts("  --cond-left-coeff <val>       Left coefficient (int16)");
	puts("  --cond-deadband <val>         Deadband around center");
	puts("  --cond-center <val>           Center point value\n");

	puts("Examples:");
	printf("  %s --effect-type constant --level 24000 --length-ms 2000\n", progname);
	printf("  %s --effect-type sine --magnitude 24000 --period-ms 100 --phase-deg 0\n", progname);
}


int main(int argc, char **argv){
	EffectArgs args;
	parse_effect_args(argc, argv, &args);

	if(args.show_help){
		print_batch_usage(argv[0]);
		return 0;
	}

	if(init())
		goto init_err;

	SDL_Haptic *haptic = get_haptic();
	if(!haptic)
		goto haptic_err;

	effect_mask supported_effects = get_supported_effects(haptic);

	if(args.noninteractive)
		run_single_effect_from_args(haptic, supported_effects, &args);
	else
		run(haptic, supported_effects);

	destroy_haptic(haptic);
haptic_err:
	cleanup();
init_err:
	return 0;
}
