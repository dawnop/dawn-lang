cuda_tile.module @m {
  entry @dtype_e5m2(%arg0: tile<ptr<f8E5M2>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = addi %5, %6 : tile<i32>
    %8 = assume div_by<16>, %arg0 : tile<ptr<f8E5M2>>
    %9 = make_tensor_view %8, shape = [512], strides = [1] : tensor_view<512xf8E5M2, strides=[1]>
    %10 = make_partition_view %9 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf8E5M2, strides=[1]>, dim_map=[0]>
    %11, %12, %13 = get_tile_block_id : tile<i32>
    %14, %15 = load_view_tko weak %10[%11] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf8E5M2, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf8E5M2>, token
    %16 = ftof %14 rounding<nearest_even> : tile<128xf8E5M2> -> tile<128xf64>
    %17 = reshape %7 : tile<i32> -> tile<1xi32>
    %18 = broadcast %17 : tile<1xi32> -> tile<128xi32>
    %19 = iota : tile<128xi32>
    %20 = addi %18, %19 : tile<128xi32>
    %21 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %22 = broadcast %21 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %23 = offset %22, %20 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %24 = store_ptr_tko weak %23, %16 token=%15 : tile<128xptr<f64>>, tile<128xf64> -> token
    %25 = constant <i32: 512> : tile<i32>
    %26 = addi %5, %25 : tile<i32>
    %27 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %28 = make_tensor_view %27, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %29 = make_partition_view %28 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %30, %31 = load_view_tko weak %29[%11] token=%24 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %32 = ftof %30 rounding<nearest_even> : tile<128xf64> -> tile<128xf8E5M2>
    %33 = ftof %32 rounding<nearest_even> : tile<128xf8E5M2> -> tile<128xf64>
    %34 = reshape %26 : tile<i32> -> tile<1xi32>
    %35 = broadcast %34 : tile<1xi32> -> tile<128xi32>
    %36 = iota : tile<128xi32>
    %37 = addi %35, %36 : tile<128xi32>
    %38 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %39 = broadcast %38 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %40 = offset %39, %37 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %41 = store_ptr_tko weak %40, %33 token=%31 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
