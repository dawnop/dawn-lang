cuda_tile.module @m {
  entry @mathops(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
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
    %14 = exp %7 : tile<128xf64>
    %15 = exp2 %7 : tile<128xf64>
    %16 = addf %14, %15 rounding<nearest_even> : tile<128xf64>
    %17 = log %7 : tile<128xf64>
    %18 = addf %16, %17 rounding<nearest_even> : tile<128xf64>
    %19 = log2 %7 : tile<128xf64>
    %20 = addf %18, %19 rounding<nearest_even> : tile<128xf64>
    %21 = sqrt %7 rounding<nearest_even> : tile<128xf64>
    %22 = addf %20, %21 rounding<nearest_even> : tile<128xf64>
    %23 = rsqrt %7 : tile<128xf64>
    %24 = addf %22, %23 rounding<nearest_even> : tile<128xf64>
    %25 = tanh %7 : tile<128xf64>
    %26 = addf %24, %25 rounding<nearest_even> : tile<128xf64>
    %27 = fpowf %7, %12 : tile<128xf64>
    %28 = addf %26, %27 rounding<nearest_even> : tile<128xf64>
    %29 = floor %12 : tile<128xf64>
    %30 = addf %28, %29 rounding<nearest_even> : tile<128xf64>
    %31 = ceil %12 : tile<128xf64>
    %32 = addf %30, %31 rounding<nearest_even> : tile<128xf64>
    %33 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %34 = make_tensor_view %33, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %35 = make_partition_view %34 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %36 = store_view_tko weak %32, %35[%4] token=%13 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
