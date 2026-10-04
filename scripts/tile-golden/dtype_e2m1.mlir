cuda_tile.module @m {
  entry @dtype_e2m1(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [64], strides = [1] : tensor_view<64xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(16), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(16), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<16xi32>, token
    %14 = pack %12 : tile<16xi32> -> tile<64xi8>
    %15 = unpack %14 : tile<64xi8> -> tile<128xf4E2M1FN>
    %16 = constant <i32: 0> : tile<i32>
    %17 = addi %5, %16 : tile<i32>
    %18 = ftof %15 rounding<nearest_even> : tile<128xf4E2M1FN> -> tile<128xf64>
    %19 = reshape %17 : tile<i32> -> tile<1xi32>
    %20 = broadcast %19 : tile<1xi32> -> tile<128xi32>
    %21 = iota : tile<128xi32>
    %22 = addi %20, %21 : tile<128xi32>
    %23 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %24 = broadcast %23 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %25 = offset %24, %22 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %26 = store_ptr_tko weak %25, %18 token=%13 : tile<128xptr<f64>>, tile<128xf64> -> token
    %27 = constant <i32: 512> : tile<i32>
    %28 = addi %5, %27 : tile<i32>
    %29 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %31 = make_partition_view %30 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %32, %33 = load_view_tko weak %31[%9] token=%26 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %34 = ftof %32 rounding<nearest_even> : tile<128xf64> -> tile<128xf4E2M1FN>
    %35 = ftof %34 rounding<nearest_even> : tile<128xf4E2M1FN> -> tile<128xf64>
    %36 = reshape %28 : tile<i32> -> tile<1xi32>
    %37 = broadcast %36 : tile<1xi32> -> tile<128xi32>
    %38 = iota : tile<128xi32>
    %39 = addi %37, %38 : tile<128xi32>
    %40 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %41 = broadcast %40 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %42 = offset %41, %39 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %43 = store_ptr_tko weak %42, %35 token=%33 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
