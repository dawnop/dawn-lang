cuda_tile.module @m {
  entry @attr_nan(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %15 = make_tensor_view %14, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%9] token=%13 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %19 = cmpf equal ordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %20 = exti %19 unsigned : tile<128xi1> -> tile<128xi32>
    %21 = itof %20 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %22, %23, %24 = get_num_tile_blocks : tile<i32>
    %25 = constant <i32: 2048> : tile<i32>
    %26 = muli %22, %25 : tile<i32>
    %27 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %28 = make_tensor_view %27, shape = [%26], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %29 = make_partition_view %28 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %30 = constant <i32: 16> : tile<i32>
    %31 = muli %9, %30 : tile<i32>
    %32 = store_view_tko weak %21, %29[%31] token=%18 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %33 = cmpf not_equal ordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %34 = exti %33 unsigned : tile<128xi1> -> tile<128xi32>
    %35 = itof %34 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %36 = constant <i32: 16> : tile<i32>
    %37 = muli %9, %36 : tile<i32>
    %38 = constant <i32: 1> : tile<i32>
    %39 = addi %37, %38 : tile<i32>
    %40 = store_view_tko weak %35, %29[%39] token=%32 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %41 = cmpf less_than ordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %42 = exti %41 unsigned : tile<128xi1> -> tile<128xi32>
    %43 = itof %42 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %44 = constant <i32: 16> : tile<i32>
    %45 = muli %9, %44 : tile<i32>
    %46 = constant <i32: 2> : tile<i32>
    %47 = addi %45, %46 : tile<i32>
    %48 = store_view_tko weak %43, %29[%47] token=%40 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %49 = cmpf less_than_or_equal ordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %50 = exti %49 unsigned : tile<128xi1> -> tile<128xi32>
    %51 = itof %50 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %52 = constant <i32: 16> : tile<i32>
    %53 = muli %9, %52 : tile<i32>
    %54 = constant <i32: 3> : tile<i32>
    %55 = addi %53, %54 : tile<i32>
    %56 = store_view_tko weak %51, %29[%55] token=%48 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %57 = cmpf greater_than ordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %58 = exti %57 unsigned : tile<128xi1> -> tile<128xi32>
    %59 = itof %58 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %60 = constant <i32: 16> : tile<i32>
    %61 = muli %9, %60 : tile<i32>
    %62 = constant <i32: 4> : tile<i32>
    %63 = addi %61, %62 : tile<i32>
    %64 = store_view_tko weak %59, %29[%63] token=%56 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %65 = cmpf greater_than_or_equal ordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %66 = exti %65 unsigned : tile<128xi1> -> tile<128xi32>
    %67 = itof %66 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %68 = constant <i32: 16> : tile<i32>
    %69 = muli %9, %68 : tile<i32>
    %70 = constant <i32: 5> : tile<i32>
    %71 = addi %69, %70 : tile<i32>
    %72 = store_view_tko weak %67, %29[%71] token=%64 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %73 = cmpf equal unordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %74 = exti %73 unsigned : tile<128xi1> -> tile<128xi32>
    %75 = itof %74 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %76 = constant <i32: 16> : tile<i32>
    %77 = muli %9, %76 : tile<i32>
    %78 = constant <i32: 6> : tile<i32>
    %79 = addi %77, %78 : tile<i32>
    %80 = store_view_tko weak %75, %29[%79] token=%72 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %81 = cmpf not_equal unordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %82 = exti %81 unsigned : tile<128xi1> -> tile<128xi32>
    %83 = itof %82 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %84 = constant <i32: 16> : tile<i32>
    %85 = muli %9, %84 : tile<i32>
    %86 = constant <i32: 7> : tile<i32>
    %87 = addi %85, %86 : tile<i32>
    %88 = store_view_tko weak %83, %29[%87] token=%80 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %89 = cmpf less_than unordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %90 = exti %89 unsigned : tile<128xi1> -> tile<128xi32>
    %91 = itof %90 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %92 = constant <i32: 16> : tile<i32>
    %93 = muli %9, %92 : tile<i32>
    %94 = constant <i32: 8> : tile<i32>
    %95 = addi %93, %94 : tile<i32>
    %96 = store_view_tko weak %91, %29[%95] token=%88 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %97 = cmpf less_than_or_equal unordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %98 = exti %97 unsigned : tile<128xi1> -> tile<128xi32>
    %99 = itof %98 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %100 = constant <i32: 16> : tile<i32>
    %101 = muli %9, %100 : tile<i32>
    %102 = constant <i32: 9> : tile<i32>
    %103 = addi %101, %102 : tile<i32>
    %104 = store_view_tko weak %99, %29[%103] token=%96 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %105 = cmpf greater_than unordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %106 = exti %105 unsigned : tile<128xi1> -> tile<128xi32>
    %107 = itof %106 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %108 = constant <i32: 16> : tile<i32>
    %109 = muli %9, %108 : tile<i32>
    %110 = constant <i32: 10> : tile<i32>
    %111 = addi %109, %110 : tile<i32>
    %112 = store_view_tko weak %107, %29[%111] token=%104 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %113 = cmpf greater_than_or_equal unordered %12, %17 : tile<128xf64> -> tile<128xi1>
    %114 = exti %113 unsigned : tile<128xi1> -> tile<128xi32>
    %115 = itof %114 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %116 = constant <i32: 16> : tile<i32>
    %117 = muli %9, %116 : tile<i32>
    %118 = constant <i32: 11> : tile<i32>
    %119 = addi %117, %118 : tile<i32>
    %120 = store_view_tko weak %115, %29[%119] token=%112 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %121 = maxf %12, %17 : tile<128xf64>
    %122 = constant <i32: 16> : tile<i32>
    %123 = muli %9, %122 : tile<i32>
    %124 = constant <i32: 12> : tile<i32>
    %125 = addi %123, %124 : tile<i32>
    %126 = store_view_tko weak %121, %29[%125] token=%120 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %127 = maxf %12, %17 propagate_nan : tile<128xf64>
    %128 = constant <i32: 16> : tile<i32>
    %129 = muli %9, %128 : tile<i32>
    %130 = constant <i32: 13> : tile<i32>
    %131 = addi %129, %130 : tile<i32>
    %132 = store_view_tko weak %127, %29[%131] token=%126 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %133 = minf %12, %17 : tile<128xf64>
    %134 = constant <i32: 16> : tile<i32>
    %135 = muli %9, %134 : tile<i32>
    %136 = constant <i32: 14> : tile<i32>
    %137 = addi %135, %136 : tile<i32>
    %138 = store_view_tko weak %133, %29[%137] token=%132 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %139 = minf %12, %17 propagate_nan : tile<128xf64>
    %140 = constant <i32: 16> : tile<i32>
    %141 = muli %9, %140 : tile<i32>
    %142 = constant <i32: 15> : tile<i32>
    %143 = addi %141, %142 : tile<i32>
    %144 = store_view_tko weak %139, %29[%143] token=%138 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
