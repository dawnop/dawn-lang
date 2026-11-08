cuda_tile.module @m {
  entry @mmaf_scaled_e5m2_acc(%arg0: tile<ptr<f8E5M2>>, %arg1: tile<ptr<f8E5M2>>, %arg2: tile<ptr<f8E8M0FNU>>, %arg3: tile<ptr<f8E8M0FNU>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f8E5M2>>
    %2 = make_tensor_view %1, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf8E5M2, strides=[64, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf8E5M2, strides=[64, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %8] token=%0 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf8E5M2, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x64xf8E5M2>, token
    %12 = assume div_by<16>, %arg1 : tile<ptr<f8E5M2>>
    %13 = make_tensor_view %12, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf8E5M2, strides=[64, 1]>
    %14 = make_partition_view %13 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf8E5M2, strides=[64, 1]>, dim_map=[0, 1]>
    %15, %16 = load_view_tko weak %14[%4, %8] token=%0 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf8E5M2, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x64xf8E5M2>, token
    %17 = constant <i32: 0> : tile<i32>
    %18 = reshape %17 : tile<i32> -> tile<1x1xi32>
    %19 = broadcast %18 : tile<1x1xi32> -> tile<64x64xi32>
    %20 = iota : tile<64xi32>
    %21 = reshape %20 : tile<64xi32> -> tile<64x1xi32>
    %22 = broadcast %21 : tile<64x1xi32> -> tile<64x64xi32>
    %23 = constant <i32: 64> : tile<64x64xi32>
    %24 = muli %22, %23 : tile<64x64xi32>
    %25 = addi %19, %24 : tile<64x64xi32>
    %26 = iota : tile<64xi32>
    %27 = reshape %26 : tile<64xi32> -> tile<1x64xi32>
    %28 = broadcast %27 : tile<1x64xi32> -> tile<64x64xi32>
    %29 = addi %25, %28 : tile<64x64xi32>
    %30 = constant <i32: 1> : tile<64x64xi32>
    %31 = addi %29, %30 : tile<64x64xi32>
    %32 = itof %31 signed rounding<nearest_even> : tile<64x64xi32> -> tile<64x64xf32>
    %33 = constant <i32: 2> : tile<64x64xi32>
    %34 = remi %29, %33 signed : tile<64x64xi32>
    %35 = constant <i32: 0> : tile<64x64xi32>
    %36 = cmpi equal %34, %35, signed : tile<64x64xi32> -> tile<64x64xi1>
    %37 = constant <f32: 0.0> : tile<64x64xf32>
    %38 = subf %37, %32 rounding<nearest_even> : tile<64x64xf32>
    %39 = select %36, %32, %38 : tile<64x64xi1>, tile<64x64xf32>
    %40 = assume div_by<16>, %arg2 : tile<ptr<f8E8M0FNU>>
    %41 = make_tensor_view %40, shape = [64, 2], strides = [2, 1] : tensor_view<64x2xf8E8M0FNU, strides=[2, 1]>
    %42 = make_partition_view %41 : partition_view<tile=(64x2), padding_value = zero, tensor_view<64x2xf8E8M0FNU, strides=[2, 1]>, dim_map=[0, 1]>
    %43, %44 = load_view_tko weak %42[%4, %8] token=%0 : partition_view<tile=(64x2), padding_value = zero, tensor_view<64x2xf8E8M0FNU, strides=[2, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x2xf8E8M0FNU>, token
    %45 = assume div_by<16>, %arg3 : tile<ptr<f8E8M0FNU>>
    %46 = make_tensor_view %45, shape = [2, 64], strides = [64, 1] : tensor_view<2x64xf8E8M0FNU, strides=[64, 1]>
    %47 = make_partition_view %46 : partition_view<tile=(2x64), padding_value = zero, tensor_view<2x64xf8E8M0FNU, strides=[64, 1]>, dim_map=[0, 1]>
    %48, %49 = load_view_tko weak %47[%4, %8] token=%0 : partition_view<tile=(2x64), padding_value = zero, tensor_view<2x64xf8E8M0FNU, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<2x64xf8E8M0FNU>, token
    %50 = mmaf_scaled %10, %15, %39, %43, %48 : tile<64x64xf8E5M2>, tile<64x64xf8E5M2>, tile<64x64xf32>, tile<64x2xf8E8M0FNU>, tile<2x64xf8E8M0FNU>
    %51 = ftof %50 rounding<nearest_even> : tile<64x64xf32> -> tile<64x64xf64>
    %52 = assume div_by<16>, %arg4 : tile<ptr<f64>>
    %53 = make_tensor_view %52, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %54 = make_partition_view %53 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %55 = store_view_tko weak %51, %54[%4, %8] token=%0 : tile<64x64xf64>, partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
