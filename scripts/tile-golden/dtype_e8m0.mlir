cuda_tile.module @m {
  entry @dtype_e8m0(%arg0: tile<ptr<f8E8M0FNU>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = addi %5, %6 : tile<i32>
    %8 = assume div_by<16>, %arg0 : tile<ptr<f8E8M0FNU>>
    %9 = make_tensor_view %8, shape = [512], strides = [1] : tensor_view<512xf8E8M0FNU, strides=[1]>
    %10 = make_partition_view %9 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf8E8M0FNU, strides=[1]>, dim_map=[0]>
    %11, %12, %13 = get_tile_block_id : tile<i32>
    %14, %15 = load_view_tko weak %10[%11] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf8E8M0FNU, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf8E8M0FNU>, token
    %16 = ftof %14 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf64>
    %17 = reshape %7 : tile<i32> -> tile<1xi32>
    %18 = broadcast %17 : tile<1xi32> -> tile<128xi32>
    %19 = iota : tile<128xi32>
    %20 = addi %18, %19 : tile<128xi32>
    %21 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %22 = broadcast %21 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %23 = offset %22, %20 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %24 = store_ptr_tko weak %23, %16 token=%15 : tile<128xptr<f64>>, tile<128xf64> -> token
    %25 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %26 = make_tensor_view %25, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %27 = make_partition_view %26 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %28, %29 = load_view_tko weak %27[%11] token=%24 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %30 = ftof %28 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %31 = ftof %30 rounding<zero> : tile<128xf32> -> tile<128xf8E8M0FNU>
    %32 = constant <i32: 512> : tile<i32>
    %33 = addi %5, %32 : tile<i32>
    %34 = ftof %31 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf32>
    %35 = ftof %34 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %36 = reshape %33 : tile<i32> -> tile<1xi32>
    %37 = broadcast %36 : tile<1xi32> -> tile<128xi32>
    %38 = iota : tile<128xi32>
    %39 = addi %37, %38 : tile<128xi32>
    %40 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %41 = broadcast %40 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %42 = offset %41, %39 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %43 = store_ptr_tko weak %42, %35 token=%29 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
