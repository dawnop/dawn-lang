cuda_tile.module @m {
  entry @elemops(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = subf %7, %12 rounding<nearest_even> : tile<128xf64>
    %15 = mulf %7, %12 rounding<nearest_even> : tile<128xf64>
    %16 = constant <f64: 2.0> : tile<128xf64>
    %17 = divf %15, %16 rounding<nearest_even> : tile<128xf64>
    %18 = negf %17 : tile<128xf64>
    %19 = absf %18 : tile<128xf64>
    %20 = fma %7, %16, %12 rounding<nearest_even> : tile<128xf64>
    %21 = cmpf less_than ordered %7, %12 : tile<128xf64> -> tile<128xi1>
    %22 = select %21, %14, %19 : tile<128xi1>, tile<128xf64>
    %23 = cmpf greater_than_or_equal ordered %7, %12 : tile<128xf64> -> tile<128xi1>
    %24 = select %23, %22, %20 : tile<128xi1>, tile<128xf64>
    %25 = cmpf equal ordered %7, %12 : tile<128xf64> -> tile<128xi1>
    %26 = minf %7, %12 : tile<128xf64>
    %27 = select %25, %26, %24 : tile<128xi1>, tile<128xf64>
    %28 = cmpf not_equal ordered %7, %12 : tile<128xf64> -> tile<128xi1>
    %29 = maxf %7, %12 : tile<128xf64>
    %30 = select %28, %27, %29 : tile<128xi1>, tile<128xf64>
    %31 = cmpf greater_than ordered %7, %12 : tile<128xf64> -> tile<128xi1>
    %32 = select %31, %30, %14 : tile<128xi1>, tile<128xf64>
    %33 = cmpf less_than_or_equal ordered %7, %12 : tile<128xf64> -> tile<128xi1>
    %34 = select %33, %32, %19 : tile<128xi1>, tile<128xf64>
    %35 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %36 = make_tensor_view %35, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %37 = make_partition_view %36 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %38 = store_view_tko weak %34, %37[%4] token=%13 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
