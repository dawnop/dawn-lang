cuda_tile.module @m {
  entry @erf_sweep(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [500], strides = [1] : tensor_view<500xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<500xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<500xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = absf %7 : tile<128xf64>
    %10 = constant <f64: 0.3275911> : tile<128xf64>
    %11 = constant <f64: 1.0> : tile<128xf64>
    %12 = fma %10, %9, %11 rounding<nearest_even> : tile<128xf64>
    %13 = divf %11, %12 rounding<nearest_even> : tile<128xf64>
    %14 = constant <f64: 1.061405429> : tile<128xf64>
    %15 = constant <f64: -1.453152027> : tile<128xf64>
    %16 = fma %13, %14, %15 rounding<nearest_even> : tile<128xf64>
    %17 = constant <f64: 1.421413741> : tile<128xf64>
    %18 = fma %13, %16, %17 rounding<nearest_even> : tile<128xf64>
    %19 = constant <f64: -0.284496736> : tile<128xf64>
    %20 = fma %13, %18, %19 rounding<nearest_even> : tile<128xf64>
    %21 = constant <f64: 0.254829592> : tile<128xf64>
    %22 = fma %13, %20, %21 rounding<nearest_even> : tile<128xf64>
    %23 = mulf %13, %22 rounding<nearest_even> : tile<128xf64>
    %24 = mulf %9, %9 rounding<nearest_even> : tile<128xf64>
    %25 = negf %24 : tile<128xf64>
    %26 = exp %25 : tile<128xf64>
    %27 = mulf %23, %26 rounding<nearest_even> : tile<128xf64>
    %28 = subf %11, %27 rounding<nearest_even> : tile<128xf64>
    %29 = constant <f64: 0.0> : tile<128xf64>
    %30 = cmpf less_than ordered %7, %29 : tile<128xf64> -> tile<128xi1>
    %31 = negf %28 : tile<128xf64>
    %32 = select %30, %31, %28 : tile<128xi1>, tile<128xf64>
    %33 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %34 = make_tensor_view %33, shape = [500], strides = [1] : tensor_view<500xf64, strides=[1]>
    %35 = make_partition_view %34 : partition_view<tile=(128), padding_value = zero, tensor_view<500xf64, strides=[1]>, dim_map=[0]>
    %36 = store_view_tko weak %32, %35[%4] token=%8 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<500xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
