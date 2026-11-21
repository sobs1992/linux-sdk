#ifndef KSTUB_H
#define KSTUB_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <limits.h>
#include <errno.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
typedef int8_t s8; typedef int16_t s16; typedef int32_t s32; typedef int64_t s64;
typedef int64_t ktime_t;
typedef int irqreturn_t;
typedef struct { int x; } pm_message_t;
#define IRQ_HANDLED 1
#define BIT(n) (1u << (n))
#define MSEC_PER_SEC 1000
#define __maybe_unused
#define GFP_KERNEL 0
#define IRQF_TRIGGER_HIGH 0
#define IRQF_ONESHOT 0
#define WQ_MEM_RECLAIM 0
#define WQ_FREEZABLE 0
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define min(a,b) ({ __typeof__(a) _a=(a); __typeof__(b) _b=(b); _a<_b?_a:_b; })
#define max(a,b) ({ __typeof__(a) _a=(a); __typeof__(b) _b=(b); _a>_b?_a:_b; })
#define clamp(v,lo,hi) min((__typeof__(v))max(v,lo),hi)
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#include <stddef.h>
#define dev_info(d,...) (printf("[%7.1f] I ", now_ms/1000.0), printf(__VA_ARGS__))
#define dev_warn(d,...) (printf("[%7.1f] W ", now_ms/1000.0), printf(__VA_ARGS__))
#define dev_err(d,...) (printf("[%7.1f] E ", now_ms/1000.0), printf(__VA_ARGS__))
#define dev_dbg(d,...) do{}while(0)
#define dev_err_probe(d,e,...) (e)
#define EXPORT_SYMBOL_GPL(x)
#define module_platform_driver(x)
#define MODULE_DEVICE_TABLE(a,b)
#define MODULE_AUTHOR(x)
#define MODULE_DESCRIPTION(x)
#define MODULE_LICENSE(x)
#define MODULE_ALIAS(x)
extern double now_ms;
struct device { void *of_node; struct device *parent; };
struct regmap { int x; };
struct regmap_config; struct regmap_irq_chip; struct regmap_irq_chip_data;
struct fwnode_handle;
struct of_device_id { char compatible[128]; const void *data; };
struct platform_device { struct device dev; void *drvdata; };
struct platform_driver { int (*probe)(struct platform_device*); void (*shutdown)(struct platform_device*);
	int (*suspend)(struct platform_device*, pm_message_t); int (*resume)(struct platform_device*);
	struct { const char *name; const struct of_device_id *of_match_table; } driver; };
struct work_struct { int x; };
struct delayed_work { struct work_struct work; };
struct workqueue_struct { int x; };
#define INIT_DELAYED_WORK(w,f) do{}while(0)
static inline bool queue_delayed_work(void *q, void *w, unsigned long d){return true;}
static inline bool mod_delayed_work(void *q, void *w, unsigned long d){return true;}
static inline bool cancel_delayed_work_sync(void *w){return true;}
static inline struct workqueue_struct *alloc_ordered_workqueue(const char *f, int fl, ...){static struct workqueue_struct q; return &q;}
static inline void destroy_workqueue(void *q){}
static inline unsigned long msecs_to_jiffies(unsigned m){return m;}
static inline unsigned jiffies_to_msecs(unsigned long j){return j;}
extern unsigned long jiffies;
static inline ktime_t ktime_get_boottime(void){return (ktime_t)(now_ms*1e6);}
static inline ktime_t ktime_add_ms(ktime_t t, s64 ms){return t+ms*1000000;}
static inline bool ktime_after(ktime_t a, ktime_t b){return a>b;}
static inline s64 ktime_ms_delta(ktime_t a, ktime_t b){return (a-b)/1000000;}
static inline void msleep(unsigned m){}
int regmap_read(struct regmap *m, unsigned reg, unsigned *val);
int regmap_write(struct regmap *m, unsigned reg, unsigned val);
int regmap_update_bits(struct regmap *m, unsigned reg, unsigned mask, unsigned val);
static inline int regmap_irq_get_virq(void *d, int irq){return 1;}
/* power supply */
enum power_supply_property { POWER_SUPPLY_PROP_STATUS, POWER_SUPPLY_PROP_CHARGE_TYPE, POWER_SUPPLY_PROP_HEALTH,
 POWER_SUPPLY_PROP_PRESENT, POWER_SUPPLY_PROP_ONLINE, POWER_SUPPLY_PROP_CAPACITY, POWER_SUPPLY_PROP_VOLTAGE_NOW,
 POWER_SUPPLY_PROP_VOLTAGE_OCV, POWER_SUPPLY_PROP_CURRENT_NOW, POWER_SUPPLY_PROP_CHARGE_FULL, POWER_SUPPLY_PROP_TEMP,
 POWER_SUPPLY_PROP_CHARGE_FULL_DESIGN, POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR, POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,
 POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT_MAX, POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE, POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX,
 POWER_SUPPLY_PROP_CHARGE_CONTROL_END_THRESHOLD, POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT, POWER_SUPPLY_PROP_INPUT_VOLTAGE_LIMIT,
 POWER_SUPPLY_PROP_VOLTAGE_MIN_DESIGN, POWER_SUPPLY_PROP_VOLTAGE_MAX_DESIGN, POWER_SUPPLY_PROP_CHARGE_TERM_CURRENT,
 POWER_SUPPLY_PROP_PRECHARGE_CURRENT, POWER_SUPPLY_PROP_USB_TYPE, POWER_SUPPLY_PROP_VOLTAGE_MAX, POWER_SUPPLY_PROP_CURRENT_MAX,
 POWER_SUPPLY_PROP_VOLTAGE_MIN, POWER_SUPPLY_PROP_TECHNOLOGY, POWER_SUPPLY_PROP_ENERGY_FULL_DESIGN, POWER_SUPPLY_PROP_INPUT_POWER_LIMIT,
 POWER_SUPPLY_PROP_CHARGE_NOW, POWER_SUPPLY_PROP_TIME_TO_EMPTY_NOW, POWER_SUPPLY_PROP_ENERGY_EMPTY_DESIGN };
enum { POWER_SUPPLY_STATUS_UNKNOWN, POWER_SUPPLY_STATUS_CHARGING, POWER_SUPPLY_STATUS_DISCHARGING, POWER_SUPPLY_STATUS_NOT_CHARGING, POWER_SUPPLY_STATUS_FULL };
enum { POWER_SUPPLY_CHARGE_BEHAVIOUR_AUTO, POWER_SUPPLY_CHARGE_BEHAVIOUR_INHIBIT_CHARGE, POWER_SUPPLY_CHARGE_BEHAVIOUR_FORCE_DISCHARGE };
enum { POWER_SUPPLY_HEALTH_UNKNOWN, POWER_SUPPLY_HEALTH_GOOD, POWER_SUPPLY_HEALTH_OVERHEAT, POWER_SUPPLY_HEALTH_OVERVOLTAGE, POWER_SUPPLY_HEALTH_SAFETY_TIMER_EXPIRE, POWER_SUPPLY_HEALTH_COLD, POWER_SUPPLY_HEALTH_UNSPEC_FAILURE };
enum { POWER_SUPPLY_CHARGE_TYPE_UNKNOWN, POWER_SUPPLY_CHARGE_TYPE_NONE, POWER_SUPPLY_CHARGE_TYPE_TRICKLE, POWER_SUPPLY_CHARGE_TYPE_FAST, POWER_SUPPLY_CHARGE_TYPE_STANDARD };
enum { POWER_SUPPLY_TYPE_USB, POWER_SUPPLY_TYPE_BATTERY, POWER_SUPPLY_TYPE_MAINS };
enum { POWER_SUPPLY_USB_TYPE_UNKNOWN, POWER_SUPPLY_USB_TYPE_SDP, POWER_SUPPLY_USB_TYPE_DCP, POWER_SUPPLY_USB_TYPE_CDP };
enum { POWER_SUPPLY_TECHNOLOGY_LIPO };
union power_supply_propval { int intval; const char *strval; };
struct power_supply_battery_ocv_table { int ocv; int capacity; };
#define POWER_SUPPLY_OCV_TEMP_MAX 20
struct power_supply_battery_info { int charge_full_design_uah, voltage_min_design_uv, voltage_max_design_uv,
 factory_internal_resistance_uohm, constant_charge_voltage_max_uv, constant_charge_current_max_ua, charge_term_current_ua,
 precharge_current_ua, energy_full_design_uwh; struct power_supply_battery_ocv_table *ocv_table[POWER_SUPPLY_OCV_TEMP_MAX];
 int ocv_table_size[POWER_SUPPLY_OCV_TEMP_MAX]; int ocv_temp[POWER_SUPPLY_OCV_TEMP_MAX]; };
struct power_supply { struct power_supply_battery_info *battery_info; void *drv_data; };
struct power_supply_desc { const char *name; int type; const enum power_supply_property *properties; size_t num_properties;
 int (*get_property)(struct power_supply*, enum power_supply_property, union power_supply_propval*);
 int (*set_property)(struct power_supply*, enum power_supply_property, const union power_supply_propval*);
 int (*property_is_writeable)(struct power_supply*, enum power_supply_property);
 void (*external_power_changed)(struct power_supply*); unsigned usb_types; unsigned charge_behaviours; char **supplied_to; size_t num_supplicants; };
struct power_supply_config { void *drv_data; struct fwnode_handle *fwnode; char **supplied_to; size_t num_supplicants; };
#define BIT_ULL(n) (1ull<<(n))
static inline void power_supply_changed(struct power_supply *p){}
static inline void *power_supply_get_drvdata(struct power_supply *p){return p->drv_data;}
int power_supply_batinfo_ocv2cap(struct power_supply_battery_info *info, int ocv, int temp);
static inline int power_supply_get_property_from_supplier(struct power_supply *p, enum power_supply_property pp, union power_supply_propval *v){return -1;}
#define IS_ERR(p) (0)
#define PTR_ERR(p) (0)
static inline void *dev_get_drvdata(struct device *d){return 0;}
static inline void *platform_get_drvdata(struct platform_device *p){return p->drvdata;}
static inline void platform_set_drvdata(struct platform_device *p, void *d){p->drvdata=d;}
static inline void *devm_kzalloc(struct device *d, size_t s, int f){return calloc(1,s);}
static inline struct fwnode_handle *dev_fwnode(struct device *d){return 0;}
static inline struct power_supply *devm_power_supply_register(struct device *d, const struct power_supply_desc *de, const struct power_supply_config *c){return 0;}
static inline int devm_request_threaded_irq(struct device *d, int irq, void *h, void *t, int f, const char *n, void *dd){return 0;}
static inline int enable_irq_wake(int irq){return 0;}
static inline bool device_property_read_bool(struct device *d, const char *n){return false;}
struct property { int length; };
struct device_node;
static inline struct property *of_find_property(const void *n, const char *name, int *len){return 0;}
static inline int of_property_read_u32(const void *n, const char *name, u32 *v){return -1;}
static inline int of_property_read_u32_index(const void *n, const char *name, int i, u32 *v){return -1;}
static inline int fixp_linear_interpolate(int x0, int y0, int x1, int y1, int x)
{ if (y0 == y1 || x == x0) return y0; if (x1 == x0 || x == x1) return y1; return y0 + ((y1 - y0) * (x - x0) / (x1 - x0)); }
#endif
