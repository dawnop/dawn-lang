cuda_tile.module @m {
  entry @llama_rms(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = mulf %12, %12 rounding<nearest_even> : tile<128xf64>
    %15 = reduce %14 dim=0 identities=[0.0 : f64] : tile<128xf64> -> tile<f64> (%16: tile<f64>, %17: tile<f64>) {
      %18 = addf %16, %17 rounding<nearest_even> : tile<f64>
      yield %18 : tile<f64>
    }
    %19 = constant <f64: 128.0> : tile<f64>
    %20 = divf %15, %19 rounding<nearest_even> : tile<f64>
    %21 = constant <f64: 1.0E-5> : tile<f64>
    %22 = addf %20, %21 rounding<nearest_even> : tile<f64>
    %23 = rsqrt %22 : tile<f64>
    %24 = reshape %23 : tile<f64> -> tile<1xf64>
    %25 = broadcast %24 : tile<1xf64> -> tile<128xf64>
    %26 = mulf %12, %25 rounding<nearest_even> : tile<128xf64>
    %27 = constant <i32: 0> : tile<i32>
    %28 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %29 = make_tensor_view %28, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %30 = make_partition_view %29 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %31, %32 = load_view_tko weak %30[%27] token=%13 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %33 = mulf %26, %31 rounding<nearest_even> : tile<128xf64>
    %34 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %35 = make_tensor_view %34, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %36 = make_partition_view %35 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %37 = store_view_tko weak %33, %36[%9] token=%32 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
